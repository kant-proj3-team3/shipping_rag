import { useCallback, useEffect, useRef, useState } from "react";

import type { UseChatHistoryResult } from "./useChatHistory";
import type { Conversation } from "../lib/chat";
import { sortByRecent } from "../lib/history";

/** 삭제 뒤 실행 취소를 받는 시간 */
export const UNDO_DELETE_MS = 5_000;

/** 방금 지워서 실행 취소할 수 있는 대화 */
export interface DeletedConversation {
  conversation: Conversation;
  /** 실행 취소를 그만 받는 시각(ms, Date.now 기준) */
  deadline: number;
}

/** useUndoDelete 가 돌려주는 삭제 상태와 동작 */
export interface UseUndoDeleteResult {
  /** 방금 지워서 실행 취소할 수 있는 대화. 없으면 undefined */
  lastDeleted: DeletedConversation | undefined;
  /** 대화를 지우고 UNDO_DELETE_MS 동안 실행 취소를 받는다. 없는 id 면 아무 일도 없다 */
  remove: (id: string) => void;
  /** 방금 지운 대화를 되돌린다. 목록은 최근 활동순이라 원래 자리로 돌아가고, 보고 있던 대화였으면 다시 연다 */
  undoRemove: () => void;
}

// 지운 기록. 지울 때 보고 있던 대화였으면 실행 취소할 때 다시 연다
interface Deletion extends DeletedConversation {
  wasCurrent: boolean;
}

/** 대화 삭제와 실행 취소 */
export function useUndoDelete({
  historyRef,
  updateHistory,
}: Pick<UseChatHistoryResult, "historyRef" | "updateHistory">): UseUndoDeleteResult {
  const [deletion, setDeletion] = useState<Deletion>();
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  // useChat 이 memo 된 HistoryList 에 넘기는 remove 의 의존성이라 렌더마다 새로 만들지 않는다
  const remove = useCallback(
    (id: string) => {
      const conversation = historyRef.current.conversations.find((c) => c.id === id);
      if (!conversation) {
        return;
      }
      const wasCurrent = historyRef.current.currentId === id;
      updateHistory(
        (h) => ({
          currentId: h.currentId === id ? undefined : h.currentId,
          conversations: h.conversations.filter((c) => c.id !== id),
        }),
        true,
      );
      setDeletion({ conversation, deadline: Date.now() + UNDO_DELETE_MS, wasCurrent });
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setDeletion(undefined), UNDO_DELETE_MS);
    },
    [historyRef, updateHistory],
  );

  // 실행 취소 안내를 memo 된 HistoryList 가 그리므로 지운 대화가 바뀔 때만 새로 만든다
  const undoRemove = useCallback(() => {
    if (!deletion) {
      return;
    }
    const { conversation, wasCurrent } = deletion;
    updateHistory(
      (h) => ({
        conversations: h.conversations.some((c) => c.id === conversation.id)
          ? h.conversations
          : sortByRecent([...h.conversations, conversation]),
        // 그사이 다른 대화로 옮겼으면 그 화면을 빼앗지 않는다
        currentId: wasCurrent && h.currentId === undefined ? conversation.id : h.currentId,
      }),
      true,
    );
    setDeletion(undefined);
    clearTimeout(timerRef.current);
  }, [deletion, updateHistory]);

  return { lastDeleted: deletion, remove, undoRemove };
}
