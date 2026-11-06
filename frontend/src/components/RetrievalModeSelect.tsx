import { RETRIEVAL_MODES, type RetrievalMode } from "../api/types";
import { RETRIEVAL_MODE_NAMES } from "../lib/labels";

interface RetrievalModeSelectProps {
  value: RetrievalMode;
  onChange: (value: RetrievalMode) => void;
  /** 고를 수 있는 방식 (서버 /health 의 supported_modes). 없으면 세 방식 전부 */
  modes?: readonly RetrievalMode[];
  disabled?: boolean;
}

/** 검색 방식 선택 (Naive / 하이브리드 / 하이브리드 + 리랭킹). 다음 질문부터 적용된다 */
export function RetrievalModeSelect({
  value,
  onChange,
  modes = RETRIEVAL_MODES,
  disabled = false,
}: RetrievalModeSelectProps) {
  return (
    <select
      value={value}
      onChange={(e) => {
        const next = modes.find((m) => m === e.target.value);
        if (next) {
          onChange(next);
        }
      }}
      disabled={disabled}
      aria-label="검색 방식"
      className="rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900"
    >
      {modes.map((m) => (
        <option key={m} value={m}>
          {RETRIEVAL_MODE_NAMES[m]}
        </option>
      ))}
    </select>
  );
}
