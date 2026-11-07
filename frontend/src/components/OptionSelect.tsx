interface OptionSelectProps<T extends string> {
  value: T;
  /** 고를 수 있는 값. 이 순서로 보인다 */
  options: readonly T[];
  /** 값 → 화면에 보일 이름 */
  labelOf: (option: T) => string;
  onChange: (value: T) => void;
  /** 스크린 리더가 읽는 선택 상자 이름 */
  label: string;
  disabled?: boolean;
}

/** 값 목록 중 하나를 고르는 선택 상자. 목록에 없는 값은 넘기지 않는다 */
export function OptionSelect<T extends string>({
  value,
  options,
  labelOf,
  onChange,
  label,
  disabled = false,
}: OptionSelectProps<T>) {
  return (
    <select
      value={value}
      onChange={(e) => {
        const next = options.find((option) => option === e.target.value);
        if (next !== undefined) {
          onChange(next);
        }
      }}
      disabled={disabled}
      aria-label={label}
      className="rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900"
    >
      {options.map((option) => (
        <option key={option} value={option}>
          {labelOf(option)}
        </option>
      ))}
    </select>
  );
}
