import { memo } from "react";

import { useNow } from "../hooks/useNow";
import type { DeletedConversation } from "../hooks/useUndoDelete";
import { titleOf, type Conversation } from "../lib/chat";
import { sortByRecent } from "../lib/history";

/** 하루 (ms) */
const DAY_MS = 24 * 60 * 60 * 1000;

/** 실행 취소 카운트다운을 다시 그리는 간격. 1초보다 짧게 두어 숫자가 늦게 바뀌지 않게 한다 */
const COUNTDOWN_TICK_MS = 200;

interface HistoryListProps {
  conversations: Conversation[];
  currentId: string | undefined;
  /** 답변을 받는 중인 대화 (지울 수 없다) */
  activeId: string | undefined;
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
  /** 방금 지운 대화. 목록에서 원래 있던 자리에 남은 초와 실행 취소 안내를 보여 준다 */
  lastDeleted: DeletedConversation | undefined;
  onUndoRemove: () => void;
}

interface DateGroup {
  label: string;
  items: Conversation[];
}

function startOfDay(time: number): number {
  const d = new Date(time);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

function dateGroupLabel(time: number, today: number): string {
  if (time >= today) {
    return "오늘";
  }
  if (time >= today - DAY_MS) {
    return "어제";
  }
  if (time >= today - 7 * DAY_MS) {
    return "지난 7일";
  }
  return "이전";
}

/** 최신순으로 정렬된 대화를 날짜 묶음으로 (묶음 순서도 최신순) */
function groupByDate(conversations: Conversation[], now: number): DateGroup[] {
  const today = startOfDay(now);
  const groups: DateGroup[] = [];
  for (const c of conversations) {
    const label = dateGroupLabel(c.updatedAt, today);
    const last = groups.at(-1);
    if (last?.label === label) {
      last.items.push(c);
    } else {
      groups.push({ label, items: [c] });
    }
  }
  return groups;
}

/** 오늘이면 시:분, 올해면 월.일, 그 전이면 연.월.일 */
function timeLabel(time: number, now: number): string {
  const d = new Date(time);
  const pad = (n: number): string => String(n).padStart(2, "0");
  if (time >= startOfDay(now)) {
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  if (d.getFullYear() === new Date(now).getFullYear()) {
    return `${d.getMonth() + 1}.${d.getDate()}`;
  }
  return `${d.getFullYear()}.${d.getMonth() + 1}.${d.getDate()}`;
}

interface DeletedItemProps {
  title: string;
  /** 실행 취소를 그만 받는 시각(ms) */
  deadline: number;
  onUndo: () => void;
}

// 지운 대화가 있던 자리의 실행 취소 안내. 왼쪽에 실행 취소를 받는 남은 초를 보여 준다.
// 남은 초는 0 이 되기 전에 안내가 사라지므로 1 아래로는 보이지 않고, 바뀔 때마다 스크린 리더가 읽지 않게 숨긴다
function DeletedItem({ title, deadline, onUndo }: DeletedItemProps) {
  const now = useNow(COUNTDOWN_TICK_MS);
  const seconds = Math.max(1, Math.ceil((deadline - now) / 1000));
  return (
    <li>
      <div
        role="status"
        className="flex items-center gap-2 rounded-lg bg-zinc-200 py-1.5 pr-2 pl-2 text-sm dark:bg-zinc-800"
      >
        <span
          aria-hidden="true"
          className="flex size-5 shrink-0 items-center justify-center rounded-full border border-zinc-400 text-[11px] font-medium text-zinc-600 tabular-nums dark:border-zinc-500 dark:text-zinc-300"
        >
          {seconds}
        </span>
        <span className="min-w-0 flex-1 truncate text-zinc-500">삭제됨: {title}</span>
        <button
          type="button"
          onClick={onUndo}
          className="shrink-0 text-xs font-medium underline underline-offset-2"
        >
          실행 취소
        </button>
      </div>
    </li>
  );
}

// 목록에 방금 지운 대화를 다시 끼운다. 최근 활동순이라 지우기 전에 있던 자리에 들어간다
function withDeleted(
  conversations: Conversation[],
  deleted: Conversation | undefined,
): Conversation[] {
  const isListed = deleted !== undefined && conversations.some((c) => c.id === deleted.id);
  return deleted === undefined || isListed ? conversations : [...conversations, deleted];
}

function HistoryListView({
  conversations,
  currentId,
  activeId,
  onSelect,
  onRemove,
  lastDeleted,
  onUndoRemove,
}: HistoryListProps) {
  const now = useNow();
  const listed = withDeleted(conversations, lastDeleted?.conversation);
  if (listed.length === 0) {
    return <p className="px-1 text-xs text-zinc-500">아직 대화가 없습니다.</p>;
  }

  return (
    <div className="space-y-4">
      {groupByDate(sortByRecent(listed), now).map(({ label, items }) => (
        <section key={label} aria-label={label}>
          <h3 className="px-1 pb-1 text-[11px] font-medium text-zinc-500">{label}</h3>
          <ul className="space-y-0.5">
            {items.map((c) => {
              const title = titleOf(c);
              if (c === lastDeleted?.conversation) {
                return (
                  <DeletedItem
                    key={c.id}
                    title={title}
                    deadline={lastDeleted.deadline}
                    onUndo={onUndoRemove}
                  />
                );
              }
              const isSelected = c.id === currentId;
              const isActive = c.id === activeId;
              return (
                <li key={c.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onSelect(c.id)}
                    aria-current={isSelected ? "page" : undefined}
                    className={`flex w-full items-center gap-2 rounded-lg py-1.5 pr-8 pl-2 text-left text-sm ${
                      isSelected
                        ? "bg-zinc-200 font-medium dark:bg-zinc-800"
                        : "text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800/60"
                    }`}
                  >
                    {isActive ? (
                      <span className="size-1.5 shrink-0 rounded-full bg-emerald-500 motion-safe:animate-pulse">
                        <span className="sr-only">답변 받는 중 </span>
                      </span>
                    ) : null}
                    <span className="min-w-0 flex-1 truncate">{title}</span>
                    <span className="shrink-0 text-[11px] font-normal text-zinc-500 tabular-nums">
                      {timeLabel(c.updatedAt, now)}
                    </span>
                  </button>
                  {!isActive ? (
                    <button
                      type="button"
                      onClick={() => onRemove(c.id)}
                      aria-label={`대화 삭제: ${title}`}
                      className="absolute top-1/2 right-1 -translate-y-1/2 rounded-md px-1.5 py-0.5 text-xs text-zinc-500 opacity-0 group-hover:opacity-100 hover:bg-zinc-200 hover:text-zinc-800 focus-visible:opacity-100 dark:hover:bg-zinc-700 dark:hover:text-zinc-200 pointer-coarse:opacity-100"
                    >
                      ✕
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

/**
 * 대화 목록: 최신순, 오늘 · 어제 · 지난 7일 · 이전으로 묶는다. 방금 지운 대화는 그 자리에 남은 초와 실행 취소 안내로 남긴다.
 * 대화가 수백 개일 수 있어 memo 로 감싼다 (입력창에 칠 때마다 다시 그리지 않게). 넘기는 핸들러는 고정해서 넘긴다
 */
export const HistoryList = memo(HistoryListView);
