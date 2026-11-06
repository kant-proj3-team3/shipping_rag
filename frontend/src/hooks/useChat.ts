import { useRef, useState } from "react";

import { useApi } from "./useApi";
import { RequestError } from "../api/client";
import type { QueryRequest, RetrievalMode } from "../api/types";
import { answerFromResponse, isWaiting, newId, type AnswerState, type Message } from "../lib/chat";
import { logWarning } from "../lib/logger";

/** useChat 이 돌려주는 대화 상태와 동작 */
export interface UseChatResult {
  messages: Message[];
  /** 답변을 기다리는 중. 요청은 한 번에 하나다 */
  isBusy: boolean;
  /** 질문을 보낸다. 받는 중이거나 빈 질문이면 보내지 않고 false */
  send: (question: string, retrievalMode: RetrievalMode) => boolean;
  /** 받는 중인 답변을 멈춘다 */
  stop: () => void;
  /** 새 대화: 받던 답변을 멈추고 새 세션으로 화면을 비운다 */
  newChat: () => void;
}

/**
 * 한 대화(= 서버 세션 하나)의 질문 · 답변.
 * 세션 id 는 브라우저가 만들고, 같은 대화의 질문은 같은 id 로 보낸다.
 */
export function useChat(): UseChatResult {
  const api = useApi();
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const [messages, setMessages] = useState<Message[]>([]);
  const controllerRef = useRef<AbortController | null>(null);
  const isBusy = isWaiting(messages);

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
    if (text === "" || isBusy) {
      return false;
    }
    const answerId = newId();
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: "user", text },
      { id: answerId, role: "assistant", question: text, state: "pending" },
    ]);
    const controller = new AbortController();
    controllerRef.current = controller;
    void receive(answerId, { question: text, retrievalMode, sessionId }, controller);
    return true;
  }

  function stop(): void {
    controllerRef.current?.abort();
  }

  function newChat(): void {
    stop();
    setMessages([]);
    setSessionId(crypto.randomUUID());
  }

  return { messages, isBusy, send, stop, newChat };
}
