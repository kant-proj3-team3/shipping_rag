import { OptionSelect } from "./OptionSelect";
import { THEME_NAMES, THEMES, type Theme } from "../lib/labels";

interface ThemeSelectProps {
  value: Theme;
  onChange: (theme: Theme) => void;
}

/** 화면 테마 선택 (시스템 · 라이트 · 다크) */
export function ThemeSelect({ value, onChange }: ThemeSelectProps) {
  return (
    <OptionSelect
      value={value}
      options={THEMES}
      labelOf={(theme) => `테마: ${THEME_NAMES[theme]}`}
      onChange={onChange}
      label="화면 테마"
    />
  );
}
