import { useEffect, useRef, useState } from "react";

import { useApi } from "./useApi";
import { useStorage } from "./useStorage";
import { RequestError } from "../api/client";
import { SESSION_ID_PATTERN, type QueryRequest, type RetrievalMode } from "../api/types";
import {
  answerFromResponse,
  isWaiting,
  messagesFromSession,
  newId,
  type AnswerState,
  type Message,
} from "../lib/chat";
import { SESSION_STORAGE_KEY } from "../lib/config";
import { logWarning } from "../lib/logger";
import type { KeyValueStorage } from "../lib/storage";

/** 지금 대화의 세션 */
interface SessionState {
  id: string;
  /** 저장해 둔 세션의 기록을 서버에서 불러오는 중 */
  isRestoring: boolean;
}

/** useChat 이 돌려주는 대화 상태와 동작 */
export interface UseChatResult {
  messages: Message[];
  /** 저장해 둔 세션의 기록을 서버에서 불러오는 중 (처음 한 번) */
  isRestoring: boolean;
  /** 답변을 기다리는 중. 요청은 한 번에 하나다 */
  isBusy: boolean;
  /** 질문을 보낸다. 받는 중 · 불러오는 중이거나 빈 질문이면 보내지 않고 false */
  send: (question: string, retrievalMode: RetrievalMode) => boolean;
  /** 받는 중인 답변을 멈춘다 */
  stop: () => void;
  /** 새 대화: 받던 답변을 멈추고 새 세션으로 화면을 비운다 */
  newChat: () => void;
}

/**
 * 한 대화(= 서버 세션 하나)의 질문 · 답변.
 * 세션 id 는 브라우저가 만들어 저장소에 남긴다. 새로고침하면 GET /session 으로 기록을 다시 불러오고,
 * 없거나 만료된 세션이면 새 세션으로 시작한다.
 */
export function useChat(): UseChatResult {
  const api = useApi();
  const storage = useStorage();
  const [session, setSession] = useState<SessionState>(() => readSession(storage));
  const [messages, setMessages] = useState<Message[]>([]);
  const controllerRef = useRef<AbortController | null>(null);
  const isBusy = isWaiting(messages);

  useEffect(() => {
    if (!session.isRestoring) {
      return undefined;
    }
    const controller = new AbortController();
    const { id } = session;

    async function restore(): Promise<void> {
      try {
        const info = await api.getSession(id, controller.signal);
        if (info) {
          setMessages(messagesFromSession(info.turns));
          setSession({ id, isRestoring: false });
        } else {
          clearSession(storage); // 없거나 만료된 세션 → 새 세션 (다음 새로고침에 다시 묻지 않게 지운다)
          setSession({ id: crypto.randomUUID(), isRestoring: false });
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          logWarning("대화 기록을 불러오지 못했다", e);
          setSession({ id, isRestoring: false }); // 기록 없이 같은 세션으로 이어서 묻는다
        }
      }
    }

    void restore();
    return () => controller.abort();
  }, [api, storage, session]);

  function finish(id: string, next: AnswerState): void {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === id && m.role === "assistant"
          ? { id, role: "assistant", question: m.question, ...next }
          : m,
      ),
    );
  }

  async function receive(
    id: string,
    request: QueryRequest,
    controller: AbortController,
  ): Promise<void> {
    try {
      const response = await api.query(request, controller.signal);
      if (response.status === "error") {
        logWarning(`서버가 오류로 답했다 (${response.errorCode ?? "-"})`, response);
      }
      finish(id, { state: "done", answer: answerFromResponse(response) });
    } catch (e) {
      const code = e instanceof RequestError ? e.code : "bad_response";
      if (code === "aborted") {
        finish(id, { state: "stopped" });
      } else {
        logWarning("질문 요청이 실패했다", e);
        finish(id, { state: "failed", failure: code });
      }
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
      }
    }
  }

  function send(question: string, retrievalMode: RetrievalMode): boolean {
    const text = question.trim();
    if (text === "" || isBusy || session.isRestoring) {
      return false;
    }
    // 서버에 기록이 생기는 첫 질문부터 세션 id 를 남긴다 (빈 세션을 새로고침 때 다시 묻지 않게)
    writeSession(storage, session.id);
    const answerId = newId();
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: "user", text },
      { id: answerId, role: "assistant", question: text, state: "pending" },
    ]);
    const controller = new AbortController();
    controllerRef.current = controller;
    void receive(answerId, { question: text, retrievalMode, sessionId: session.id }, controller);
    return true;
  }

  function stop(): void {
    controllerRef.current?.abort();
  }

  function newChat(): void {
    stop();
    clearSession(storage);
    setMessages([]);
    setSession({ id: crypto.randomUUID(), isRestoring: false });
  }

  return { messages, isRestoring: session.isRestoring, isBusy, send, stop, newChat };
}

/** 저장해 둔 세션 id. 없거나 형식이 틀리면 새 세션 */
function readSession(storage: KeyValueStorage): SessionState {
  try {
    const stored = storage.getItem(SESSION_STORAGE_KEY);
    if (stored !== null && SESSION_ID_PATTERN.test(stored)) {
      return { id: stored, isRestoring: true };
    }
  } catch (e) {
    logWarning("저장해 둔 세션 id 를 읽지 못했다", e);
  }
  return { id: crypto.randomUUID(), isRestoring: false };
}

function writeSession(storage: KeyValueStorage, id: string): void {
  try {
    storage.setItem(SESSION_STORAGE_KEY, id);
  } catch (e) {
    logWarning("세션 id 를 저장하지 못했다", e); // 새로고침하면 새 대화로 시작할 뿐 화면은 동작한다
  }
}

function clearSession(storage: KeyValueStorage): void {
  try {
    storage.removeItem(SESSION_STORAGE_KEY);
  } catch (e) {
    logWarning("저장해 둔 세션 id 를 지우지 못했다", e);
  }
}
