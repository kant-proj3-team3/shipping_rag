import { memo } from "react";

import { useNow } from "../hooks/useNow";
import { titleOf, type Conversation } from "../lib/chat";
import { sortByRecent } from "../lib/history";

/** 하루 (ms) */
const DAY_MS = 24 * 60 * 60 * 1000;

interface HistoryListProps {
  conversations: Conversation[];
  currentId: string | undefined;
  /** 답변을 받는 중인 대화 (지울 수 없다) */
  activeId: string | undefined;
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
}

interface DateGroup {
  label: string;
  items: Conversation[];
}

/**
 * 대화 목록: 최신순, 오늘 · 어제 · 지난 7일 · 이전으로 묶는다.
 * 대화가 수백 개일 수 있어 memo 로 감싼다 (입력창에 칠 때마다 다시 그리지 않게). 넘기는 핸들러는 고정해서 넘긴다
 */
export const HistoryList = memo(HistoryListView);

function HistoryListView({
  conversations,
  currentId,
  activeId,
  onSelect,
  onRemove,
}: HistoryListProps) {
  const now = useNow();
  if (conversations.length === 0) {
    return <p className="px-1 text-xs text-zinc-500">아직 대화가 없습니다.</p>;
  }

  return (
    <div className="space-y-4">
      {groupByDate(sortByRecent(conversations), now).map(({ label, items }) => (
        <section key={label} aria-label={label}>
          <h3 className="px-1 pb-1 text-[11px] font-medium text-zinc-500">{label}</h3>
          <ul className="space-y-0.5">
            {items.map((c) => {
              const isSelected = c.id === currentId;
              const isActive = c.id === activeId;
              const title = titleOf(c);
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
