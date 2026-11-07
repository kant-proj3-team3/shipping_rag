import { OptionSelect } from "./OptionSelect";
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
    <OptionSelect
      value={value}
      options={modes}
      labelOf={(mode) => RETRIEVAL_MODE_NAMES[mode]}
      onChange={onChange}
      label="검색 방식"
      disabled={disabled}
    />
  );
}
