import type { HealthState } from "../hooks/useHealth";

const DOT_CLASS: Record<HealthState["kind"], string> = {
  checking: "bg-zinc-400 motion-safe:animate-pulse",
  ok: "bg-emerald-500",
  index_not_ready: "bg-amber-500",
  offline: "bg-red-500",
};

// 화면은 서버가 질문을 받을 수 있는지만 알면 된다. 인덱스가 없으면(index_ready=false) "준비 중"으로 묶는다
const STATUS_TEXT: Record<HealthState["kind"], string> = {
  checking: "확인 중...",
  ok: "서버 정상",
  index_not_ready: "서버 준비 중",
  offline: "연결 안 됨",
};

interface ServerStatusProps {
  state: HealthState;
}

/** 서버 상태(/health) 한 줄 */
export function ServerStatus({ state }: ServerStatusProps) {
  return (
    <p
      role="status"
      className="flex items-center gap-2 text-xs font-medium text-zinc-700 dark:text-zinc-300"
    >
      <span
        className={`size-2 shrink-0 rounded-full ${DOT_CLASS[state.kind]}`}
        aria-hidden="true"
      />
      {STATUS_TEXT[state.kind]}
    </p>
  );
}
