import { useMutation } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { useApi } from "./useApi";
import { useChatHistory } from "./useChatHistory";
import { useSessionLookup } from "./useSessionLookup";
import { useStorage } from "./useStorage";
import { useUndoDelete } from "./useUndoDelete";
import { RequestError } from "../api/client";
import type { QueryRequest, RetrievalMode } from "../api/types";
import {
  answerFromResponse,
  newId,
  titleFrom,
  type AnswerState,
  type Conversation,
  type Message,
} from "../lib/chat";
import { saveCurrentId } from "../lib/history";
import { logWarning } from "../lib/logger";
import { sessionViewOf } from "../lib/session";

/** 새 대화 화면의 메시지. 렌더마다 새 배열을 만들지 않는다 */
const NO_MESSAGES: Message[] = [];

/** 답을 받는 요청 하나 (POST /query) */
interface AskVariables {
  request: QueryRequest;
  /** 사용자가 중지하면 끊는다 */
  signal: AbortSignal;
}

/** useChat 이 돌려주는 대화 목록 상태와 동작 */
export interface UseChatResult {
  /** 질문을 한 번이라도 보낸 대화 (서버 기록으로 채운, 아직 저장하지 않은 대화 포함) */
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
 * - 대화를 열거나 새로고침하면 서버 세션을 확인한다 (useSessionLookup · lib/session.ts).
 *   브라우저에 내용이 없으면 서버 기록으로 채우고, 만료됐으면 알린 뒤 다음 질문을 새 대화로 보낸다
 */
export function useChat(): UseChatResult {
  const api = useApi();
  const storage = useStorage();
  const { history, historyRef, isStorageOk, updateHistory } = useChatHistory();
  const {
    lastDeleted,
    remove: removeConversation,
    undoRemove,
  } = useUndoDelete({ historyRef, updateHistory });
  // 세션을 확인할 대화. 대화를 열 때 정한다. 방금 보낸 대화 · 받는 중인 대화는 이 탭이 세션을 만드는 중이라 확인하지 않는다
  const [checkId, setCheckId] = useState(history.currentId);
  const lookup = useSessionLookup(checkId === history.currentId ? checkId : undefined);
  // 답을 받는 요청. 받는 중인 대화(activeId)는 이 요청 상태에서 읽는다
  const ask = useMutation({
    mutationFn: ({ request, signal }: AskVariables) => api.query(request, signal),
    // 브라우저가 오프라인이라고 해도 멈추지 않고 network 오류로 끝낸다
    networkMode: "always",
  });
  // 중지할 요청. 같은 렌더 안에서 두 번 불려도 한 번만 보내도록 보내기 여부도 이것으로 본다
  const controllerRef = useRef<AbortController | null>(null);

  const local = history.conversations.find((c) => c.id === history.currentId);
  const { status, restored } = sessionViewOf(lookup, local);
  // 브라우저에도 서버에도 없는 대화는 새 대화 화면으로 연다
  const currentId = status === "missing" ? undefined : history.currentId;
  const restoredId = restored?.id;
  const activeId = ask.isPending ? ask.variables.request.sessionId : undefined;

  useEffect(() => {
    saveCurrentId(storage, currentId);
  }, [storage, currentId]);

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
    answerId: string,
    request: QueryRequest,
    controller: AbortController,
  ): Promise<void> {
    try {
      const response = await ask.mutateAsync({ request, signal: controller.signal });
      if (response.status === "error") {
        logWarning(`서버가 오류로 답했다 (${response.errorCode ?? "-"})`, response);
      }
      finish(request.sessionId, answerId, {
        state: "done",
        answer: answerFromResponse(response),
      });
    } catch (e) {
      const code = e instanceof RequestError ? e.code : "bad_response";
      if (code === "aborted") {
        finish(request.sessionId, answerId, { state: "stopped" });
      } else {
        logWarning("질문 요청이 실패했다", e);
        finish(request.sessionId, answerId, { state: "failed", failure: code });
      }
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
      }
    }
  }

  function send(question: string, retrievalMode: RetrievalMode): boolean {
    const text = question.trim();
    if (text === "" || controllerRef.current !== null || status === "checking") {
      return false;
    }
    // 새 대화 화면이거나 만료된 대화면 새 세션으로 시작한다
    const id = currentId !== undefined && status !== "expired" ? currentId : newId();
    const existing =
      historyRef.current.conversations.find((c) => c.id === id) ??
      (restored?.id === id ? restored : undefined);
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
    setCheckId(undefined);
    const controller = new AbortController();
    controllerRef.current = controller;
    void receive(answerId, { question: text, retrievalMode, sessionId: id }, controller);
    return true;
  }

  function stop(): void {
    controllerRef.current?.abort();
  }

  function newChat(): void {
    updateHistory((h) => ({ ...h, currentId: undefined }));
    setCheckId(undefined);
  }

  // select · remove 는 memo 된 HistoryList 에 넘기므로 렌더마다 새로 만들지 않는다 (입력할 때마다 목록을 다시 그리지 않게)
  const select = useCallback(
    (id: string) => {
      if (id === historyRef.current.currentId) {
        return;
      }
      updateHistory((h) => ({ ...h, currentId: id }));
      // 받는 중인 대화는 첫 답이 오기 전이면 서버에 세션이 아직 없어 확인하지 않는다
      setCheckId(id === activeId ? undefined : id);
    },
    [activeId, historyRef, updateHistory],
  );

  const remove = useCallback(
    (id: string) => {
      if (id === activeId) {
        return;
      }
      if (id === restoredId) {
        // 서버 기록으로 채운 대화는 브라우저에 없으므로 화면에서만 닫는다
        updateHistory((h) => ({ ...h, currentId: undefined }));
        setCheckId(undefined);
        return;
      }
      removeConversation(id);
    },
    [activeId, restoredId, removeConversation, updateHistory],
  );

  return {
    conversations:
      restored === undefined ? history.conversations : [restored, ...history.conversations],
    currentId,
    messages: (local ?? restored)?.messages ?? NO_MESSAGES,
    activeId,
    isBusy: activeId !== undefined,
    isChecking: status === "checking",
    isExpired: status === "expired",
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
