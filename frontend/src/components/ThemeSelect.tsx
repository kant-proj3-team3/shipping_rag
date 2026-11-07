import { THEME_NAMES, THEMES, type Theme } from "../lib/labels";

interface ThemeSelectProps {
  value: Theme;
  onChange: (theme: Theme) => void;
}

/** 화면 테마 선택 (시스템 · 라이트 · 다크) */
export function ThemeSelect({ value, onChange }: ThemeSelectProps) {
  return (
    <select
      value={value}
      onChange={(e) => {
        const next = THEMES.find((t) => t === e.target.value);
        if (next) {
          onChange(next);
        }
      }}
      aria-label="화면 테마"
      className="rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
    >
      {THEMES.map((t) => (
        <option key={t} value={t}>
          테마: {THEME_NAMES[t]}
        </option>
      ))}
    </select>
  );
}
