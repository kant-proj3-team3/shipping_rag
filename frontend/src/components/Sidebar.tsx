import { HistoryList } from "./HistoryList";
import { ServerStatus } from "./ServerStatus";
import type { HealthState } from "../hooks/useHealth";
import { titleOf, type Conversation } from "../lib/chat";
import type { SaveResult } from "../lib/history";
import { SAVE_WARNING_TEXT } from "../lib/labels";

interface SidebarProps {
  health: HealthState;
  conversations: Conversation[];
  currentId: string | undefined;
  /** 답변을 받는 중인 대화 */
  activeId: string | undefined;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
  /** 방금 지운 대화 (실행 취소 안내) */
  lastDeleted: Conversation | undefined;
  onUndoRemove: () => void;
  /** 대화 목록의 마지막 저장 결과. saved 가 아니면 경고를 보인다 */
  saveResult: SaveResult;
}

/** 왼쪽 사이드바: 새 대화 · 대화 목록 · 서버 상태 */
export function Sidebar({
  health,
  conversations,
  currentId,
  activeId,
  onNewChat,
  onSelect,
  onRemove,
  lastDeleted,
  onUndoRemove,
  saveResult,
}: SidebarProps) {
  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="p-3">
        <button
          type="button"
          onClick={onNewChat}
          aria-current={currentId === undefined ? "page" : undefined}
          className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-left text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          + 새 대화
        </button>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-3 pb-3" aria-label="대화 목록">
        <h2 className="px-1 py-2 text-xs font-semibold text-zinc-500">대화 목록</h2>
        <HistoryList
          conversations={conversations}
          currentId={currentId}
          activeId={activeId}
          onSelect={onSelect}
          onRemove={onRemove}
        />
      </nav>

      <div className="space-y-2 border-t border-zinc-200 p-3 dark:border-zinc-800">
        {lastDeleted ? (
          <div
            role="status"
            className="flex items-center justify-between gap-2 rounded-lg bg-zinc-200 px-3 py-1.5 text-xs dark:bg-zinc-800"
          >
            <span className="min-w-0 truncate">삭제됨: {titleOf(lastDeleted)}</span>
            <button
              type="button"
              onClick={onUndoRemove}
              className="shrink-0 font-medium underline underline-offset-2"
            >
              실행 취소
            </button>
          </div>
        ) : null}
        {saveResult !== "saved" ? (
          <p role="status" className="text-xs text-amber-700 dark:text-amber-400">
            {SAVE_WARNING_TEXT[saveResult]}
          </p>
        ) : null}
        <ServerStatus state={health} />
      </div>
    </aside>
  );
}
