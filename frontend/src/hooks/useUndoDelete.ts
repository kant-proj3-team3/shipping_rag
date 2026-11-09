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
  /** 방금 지운 대화를 되돌린다. 목록은 최근 활동순이라 원래 자리로 돌아가고, 보고 있던 대화였으면 다시 연다 */
  undoRemove: () => void;
}

/** 대화 삭제와 실행 취소 */
export function useUndoDelete({
  historyRef,
  updateHistory,
}: Pick<UseChatHistoryResult, "historyRef" | "updateHistory">): UseUndoDeleteResult {
  const [lastDeleted, setLastDeleted] = useState<Conversation>();
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const wasCurrentRef = useRef(false);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  // useChat 이 memo 된 HistoryList 에 넘기는 remove 의 의존성이라 렌더마다 새로 만들지 않는다
  const remove = useCallback(
    (id: string) => {
      const conversation = historyRef.current.conversations.find((c) => c.id === id);
      if (!conversation) {
        return;
      }
      wasCurrentRef.current = historyRef.current.currentId === id;
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
      (h) => ({
        conversations: h.conversations.some((c) => c.id === lastDeleted.id)
          ? h.conversations
          : sortByRecent([...h.conversations, lastDeleted]),
        // 그사이 다른 대화로 옮겼으면 그 화면을 빼앗지 않는다
        currentId:
          wasCurrentRef.current && h.currentId === undefined ? lastDeleted.id : h.currentId,
      }),
      true,
    );
    setLastDeleted(undefined);
    clearTimeout(timerRef.current);
  }

  return { lastDeleted, remove, undoRemove };
}
