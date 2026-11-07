import { useCallback, useEffect, useRef, useState } from "react";

import type { UseChatHistoryResult } from "./useChatHistory";
import type { Conversation } from "../lib/chat";
import { sortByRecent } from "../lib/history";

/** 삭제 뒤 실행 취소를 받는 시간 */
export const UNDO_DELETE_MS = 5_000;

/** useUndoDelete 가 돌려주는 삭제 상태와 동작 */
export interface UseUndoDeleteResult {
  /** 방금 지워서 실행 취소할 수 있는 대화 */
  lastDeleted: Conversation | undefined;
  /** 대화를 지우고 UNDO_DELETE_MS 동안 실행 취소를 받는다. 없는 id 면 아무 일도 없다 */
  remove: (id: string) => void;
  /** 방금 지운 대화를 되돌린다. 목록은 최근 활동순이라 원래 자리로 돌아간다 */
  undoRemove: () => void;
}

/** 대화 삭제와 실행 취소 */
export function useUndoDelete({
  historyRef,
  updateHistory,
}: Pick<UseChatHistoryResult, "historyRef" | "updateHistory">): UseUndoDeleteResult {
  const [lastDeleted, setLastDeleted] = useState<Conversation>();
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  // useChat 이 memo 된 HistoryList 에 넘기는 remove 의 의존성이라 렌더마다 새로 만들지 않는다
  const remove = useCallback(
    (id: string) => {
      const conversation = historyRef.current.conversations.find((c) => c.id === id);
      if (!conversation) {
        return;
      }
      updateHistory(
        (h) => ({
          currentId: h.currentId === id ? undefined : h.currentId,
          conversations: h.conversations.filter((c) => c.id !== id),
        }),
        true,
      );
      setLastDeleted(conversation);
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setLastDeleted(undefined), UNDO_DELETE_MS);
    },
    [historyRef, updateHistory],
  );

  function undoRemove(): void {
    if (!lastDeleted) {
      return;
    }
    updateHistory(
      (h) =>
        h.conversations.some((c) => c.id === lastDeleted.id)
          ? h
          : { ...h, conversations: sortByRecent([...h.conversations, lastDeleted]) },
      true,
    );
    setLastDeleted(undefined);
    clearTimeout(timerRef.current);
  }

  return { lastDeleted, remove, undoRemove };
}
