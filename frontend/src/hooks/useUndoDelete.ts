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
  /** 지운 뒤 아직 실행 취소를 받는 대화들 (지운 순서). 대화마다 따로 UNDO_DELETE_MS 동안 남는다 */
  recentlyDeleted: DeletedConversation[];
  /** 대화를 지우고 UNDO_DELETE_MS 동안 실행 취소를 받는다. 없는 id 면 아무 일도 없다 */
  remove: (id: string) => void;
  /**
   * 지운 대화 하나를 되돌린다. 목록은 최근 활동순이라 원래 자리로 돌아가고, 보고 있던 대화였으면 다시 연다.
   * 실행 취소 시간이 지났거나 지운 적 없는 id 면 아무 일도 없다
   */
  undoRemove: (id: string) => void;
}

// 지운 기록. 지울 때 보고 있던 대화였으면 실행 취소할 때 다시 연다
interface Deletion extends DeletedConversation {
  wasCurrent: boolean;
}

type Timer = ReturnType<typeof setTimeout>;

/** 대화 삭제와 실행 취소. 여러 대화를 잇달아 지워도 대화마다 따로 실행 취소를 받는다 */
export function useUndoDelete({
  historyRef,
  updateHistory,
}: Pick<UseChatHistoryResult, "historyRef" | "updateHistory">): UseUndoDeleteResult {
  const [deletions, setDeletions] = useState<Deletion[]>([]);
  // 대화 id → 실행 취소 시간이 끝나면 기록을 지우는 타이머. 렌더마다 새로 만들지 않게 처음 쓸 때 한 번만 만든다
  const timersRef = useRef<Map<string, Timer>>(null);
  const timersOf = useCallback((): Map<string, Timer> => {
    timersRef.current ??= new Map();
    return timersRef.current;
  }, []);

  useEffect(() => {
    const timers = timersOf();
    return () => {
      for (const timer of timers.values()) {
        clearTimeout(timer);
      }
    };
  }, [timersOf]);

  // 지운 기록 하나를 없앤다 (실행 취소했거나 시간이 지났을 때)
  const forget = useCallback(
    (id: string) => {
      const timers = timersOf();
      clearTimeout(timers.get(id));
      timers.delete(id);
      setDeletions((prev) => prev.filter((d) => d.conversation.id !== id));
    },
    [timersOf],
  );

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
      const deletion = { conversation, deadline: Date.now() + UNDO_DELETE_MS, wasCurrent };
      setDeletions((prev) => [...prev.filter((d) => d.conversation.id !== id), deletion]);
      const timers = timersOf();
      clearTimeout(timers.get(id));
      timers.set(
        id,
        setTimeout(() => forget(id), UNDO_DELETE_MS),
      );
    },
    [historyRef, updateHistory, timersOf, forget],
  );

  // 실행 취소 안내를 memo 된 HistoryList 가 그리므로 지운 기록이 바뀔 때만 새로 만든다
  const undoRemove = useCallback(
    (id: string) => {
      const deletion = deletions.find((d) => d.conversation.id === id);
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
      forget(id);
    },
    [deletions, updateHistory, forget],
  );

  return { recentlyDeleted: deletions, remove, undoRemove };
}
