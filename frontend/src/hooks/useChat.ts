import { useCallback, useEffect, useRef, useState } from "react";

import { useApi } from "./useApi";
import { useChatHistory } from "./useChatHistory";
import { useUndoDelete } from "./useUndoDelete";
import { RequestError } from "../api/client";
import type { QueryRequest, RetrievalMode, SessionInfo } from "../api/types";
import {
  answerFromResponse,
  conversationFromSession,
  hasServerTurn,
  newId,
  titleFrom,
  type AnswerState,
  type Conversation,
  type Message,
} from "../lib/chat";
import { logWarning } from "../lib/logger";

/** 새 대화 화면의 메시지. 렌더마다 새 배열을 만들지 않는다 */
const NO_MESSAGES: Message[] = [];

/**
 * 보고 있는 대화의 서버 세션 상태.
 * - checking: GET /session 으로 확인하는 중 (보내지 않는다)
 * - live: 같은 세션으로 이어서 묻는다 (확인하지 못한 경우도 포함)
 * - expired: 서버에서 만료됐다. 다음 질문은 새 대화로 시작한다
 */
type SessionStatus = "checking" | "live" | "expired";

interface SessionCheck {
  /** 확인한 대화 id */
  id: string;
  status: SessionStatus;
}

/** useChat 이 돌려주는 대화 목록 상태와 동작 */
export interface UseChatResult {
  /** 질문을 한 번이라도 보낸 대화 */
  conversations: Conversation[];
  /** 보고 있는 대화. 없으면 새 대화 화면 */
  currentId: string | undefined;
  /** 보고 있는 대화의 메시지 */
  messages: Message[];
  /** 답변을 받는 중인 대화. 요청은 한 번에 하나다 */
  activeId: string | undefined;
  /** 답변을 받는 중 (어느 대화든) */
  isBusy: boolean;
  /** 보고 있는 대화의 서버 세션을 확인하는 중. 끝날 때까지 보내지 않는다 */
  isChecking: boolean;
  /** 보고 있는 대화가 서버에서 만료됐다. 다음 질문은 새 대화로 시작한다 */
  isExpired: boolean;
  /** 마지막 저장이 성공했는지 */
  isStorageOk: boolean;
  /** 방금 지워서 실행 취소할 수 있는 대화 */
  lastDeleted: Conversation | undefined;
  /** 보고 있는 대화에 질문을 보낸다. 받는 중 · 확인 중이거나 빈 질문이면 보내지 않고 false */
  send: (question: string, retrievalMode: RetrievalMode) => boolean;
  /** 받는 중인 답변을 멈춘다 */
  stop: () => void;
  /** 새 대화 화면. 받던 답변은 원래 대화에서 계속 받는다 */
  newChat: () => void;
  /** 다른 대화를 연다 */
  select: (id: string) => void;
  /** 대화를 지운다. 받는 중인 대화는 지우지 않는다 */
  remove: (id: string) => void;
  /** 방금 지운 대화를 되돌린다 */
  undoRemove: () => void;
}

/**
 * 대화 목록과 보내기 · 중지 · 대화 전환 · 삭제.
 * - 대화 하나 = 서버 세션 하나. 대화 id 가 곧 session_id 다
 * - 목록은 브라우저 저장소에 남긴다 (서버 기록에는 근거 · 오류 안내가 없다)
 * - 대화를 열거나 새로고침하면 GET /session 으로 세션을 확인한다. 브라우저에 내용이 없으면 서버 기록으로 채우고,
 *   만료됐으면 알린 뒤 다음 질문을 새 대화로 보낸다
 */
export function useChat(): UseChatResult {
  const api = useApi();
  const { history, historyRef, isStorageOk, updateHistory } = useChatHistory();
  const {
    lastDeleted,
    remove: removeConversation,
    undoRemove,
  } = useUndoDelete({
    historyRef,
    updateHistory,
  });
  const [activeId, setActiveId] = useState<string>();
  const [check, setCheck] = useState<SessionCheck | undefined>(() =>
    history.currentId === undefined ? undefined : { id: history.currentId, status: "checking" },
  );
  const controllerRef = useRef<AbortController | null>(null);

  const { conversations, currentId } = history;
  const statusHere = check !== undefined && check.id === currentId ? check.status : "live";
  const isChecking = currentId !== undefined && statusHere === "checking";
  const isExpired = currentId !== undefined && statusHere === "expired";
  const checkingId = check?.status === "checking" ? check.id : undefined;

  useEffect(() => {
    if (checkingId === undefined) {
      return undefined;
    }
    const id = checkingId;
    const controller = new AbortController();

    async function verify(): Promise<void> {
      let info: SessionInfo | null = null;
      let isConfirmed = true;
      try {
        info = await api.getSession(id, controller.signal);
      } catch (e) {
        if (controller.signal.aborted) {
          return;
        }
        logWarning("대화 세션을 확인하지 못했다", e);
        isConfirmed = false;
      }
      if (controller.signal.aborted) {
        return;
      }
      if (historyRef.current.currentId !== id) {
        setCheck(undefined); // 확인하는 사이 다른 탭에서 지워져 이 대화를 보고 있지 않다
        return;
      }
      const local = historyRef.current.conversations.find((c) => c.id === id);
      if (local !== undefined) {
        // 서버가 답한 적 없는 대화는 404 여도 세션이 아직 없을 뿐이다. 확인하지 못했으면 같은 세션으로 이어서 묻는다
        const isGone = isConfirmed && info === null && hasServerTurn(local.messages);
        setCheck({ id, status: isGone ? "expired" : "live" });
        return;
      }
      if (info !== null && info.turns.length > 0) {
        const restored = conversationFromSession(info); // 브라우저에 남은 내용이 없으면 서버 기록으로 채운다
        updateHistory(
          (h) => ({
            ...h,
            conversations: [restored, ...h.conversations.filter((c) => c.id !== id)],
          }),
          true,
        );
        setCheck({ id, status: "live" });
        return;
      }
      // 브라우저에도 없고 서버 기록으로도 채우지 못했다 → 새 대화 화면 (보이지 않는 옛 세션으로 묻지 않게)
      updateHistory((h) => (h.currentId === id ? { ...h, currentId: undefined } : h));
      setCheck(undefined);
    }

    void verify();
    return () => controller.abort();
  }, [api, checkingId, historyRef, updateHistory]);

  function finish(conversationId: string, answerId: string, next: AnswerState): void {
    updateHistory(
      (h) => ({
        ...h,
        conversations: h.conversations.map((c) =>
          c.id === conversationId
            ? {
                ...c,
                updatedAt: Date.now(),
                messages: c.messages.map((m) =>
                  m.id === answerId && m.role === "assistant"
                    ? { id: m.id, role: "assistant", question: m.question, ...next }
                    : m,
                ),
              }
            : c,
        ),
      }),
      true,
    );
  }

  async function receive(
    conversationId: string,
    answerId: string,
    request: QueryRequest,
    controller: AbortController,
  ): Promise<void> {
    try {
      const response = await api.query(request, controller.signal);
      if (response.status === "error") {
        logWarning(`서버가 오류로 답했다 (${response.errorCode ?? "-"})`, response);
      }
      finish(conversationId, answerId, { state: "done", answer: answerFromResponse(response) });
    } catch (e) {
      const code = e instanceof RequestError ? e.code : "bad_response";
      if (code === "aborted") {
        finish(conversationId, answerId, { state: "stopped" });
      } else {
        logWarning("질문 요청이 실패했다", e);
        finish(conversationId, answerId, { state: "failed", failure: code });
      }
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        setActiveId(undefined);
      }
    }
  }

  function send(question: string, retrievalMode: RetrievalMode): boolean {
    const text = question.trim();
    // 받는 중인지는 ref 로 본다: 같은 렌더 안에서 두 번 불려도 한 번만 보낸다
    if (text === "" || controllerRef.current !== null || isChecking) {
      return false;
    }
    const { conversations: latest, currentId: latestId } = historyRef.current;
    // 새 대화 화면이거나 만료된 대화면 새 세션으로 시작한다
    const id = latestId !== undefined && !isExpired ? latestId : newId();
    const existing = latest.find((c) => c.id === id);
    const answerId = newId();
    const conversation: Conversation = {
      id,
      title: existing?.title ?? titleFrom(text),
      updatedAt: Date.now(),
      messages: [
        ...(existing?.messages ?? []),
        { id: newId(), role: "user", text },
        { id: answerId, role: "assistant", question: text, state: "pending" },
      ],
    };
    // 답을 받는 도중 탭이 닫혀도 질문은 남도록 바로 저장한다
    updateHistory(
      (h) => ({
        currentId: id,
        conversations: [conversation, ...h.conversations.filter((c) => c.id !== id)],
      }),
      true,
    );
    if (id !== latestId) {
      setCheck({ id, status: "live" });
    }
    const controller = new AbortController();
    controllerRef.current = controller;
    setActiveId(id);
    void receive(id, answerId, { question: text, retrievalMode, sessionId: id }, controller);
    return true;
  }

  function stop(): void {
    controllerRef.current?.abort();
  }

  function newChat(): void {
    updateHistory((h) => ({ ...h, currentId: undefined }));
    setCheck(undefined);
  }

  // select · remove 는 memo 된 HistoryList 에 넘기므로 렌더마다 새로 만들지 않는다 (입력할 때마다 목록을 다시 그리지 않게)
  const select = useCallback(
    (id: string) => {
      if (id === historyRef.current.currentId) {
        return;
      }
      updateHistory((h) => ({ ...h, currentId: id }));
      // 받는 중인 대화는 첫 답이 오기 전이면 서버에 세션이 아직 없어 확인하지 않는다
      setCheck({ id, status: id === activeId ? "live" : "checking" });
    },
    [activeId, historyRef, updateHistory],
  );

  const remove = useCallback(
    (id: string) => {
      if (id === activeId) {
        return;
      }
      removeConversation(id);
      setCheck((c) => (c?.id === id ? undefined : c)); // 확인 중이던 대화면 확인을 멈춘다
    },
    [activeId, removeConversation],
  );

  return {
    conversations,
    currentId,
    messages: conversations.find((c) => c.id === currentId)?.messages ?? NO_MESSAGES,
    activeId,
    isBusy: activeId !== undefined,
    isChecking,
    isExpired,
    isStorageOk,
    lastDeleted,
    send,
    stop,
    newChat,
    select,
    remove,
    undoRemove,
  };
}
