import { useEffect, useState } from "react";

import { useMediaQuery } from "./useMediaQuery";
import { useStorage } from "./useStorage";
import { THEME_STORAGE_KEY } from "../lib/config";
import { THEMES, type Theme } from "../lib/labels";
import { logWarning } from "../lib/logger";
import type { KeyValueStorage } from "../lib/storage";

/** useTheme 이 돌려주는 선택값과 변경 함수 */
export interface UseThemeResult {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

function readTheme(storage: KeyValueStorage): Theme {
  try {
    const value = storage.getItem(THEME_STORAGE_KEY);
    return THEMES.find((t) => t !== "system" && t === value) ?? "system";
  } catch (e) {
    logWarning("저장된 테마를 읽지 못했다", e);
    return "system";
  }
}

/**
 * 화면 테마 (시스템 · 라이트 · 다크). 고른 값은 저장소에 남긴다.
 * <html> 에 dark 클래스와 color-scheme(스크롤바 · 폼 요소 색)을 맞추고, "시스템"이면 OS 설정이 바뀌는 대로 따라간다.
 * 처음 그리기 전에는 index.html 의 스크립트가 같은 규칙으로 붙인다
 */
export function useTheme(): UseThemeResult {
  const storage = useStorage();
  const [theme, setTheme] = useState<Theme>(() => readTheme(storage));
  const prefersDark = useMediaQuery("(prefers-color-scheme: dark)", false);
  const isDark = theme === "dark" || (theme === "system" && prefersDark);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", isDark);
    root.style.colorScheme = isDark ? "dark" : "light";
  }, [isDark]);

  function selectTheme(next: Theme): void {
    setTheme(next);
    try {
      if (next === "system") {
        storage.removeItem(THEME_STORAGE_KEY);
      } else {
        storage.setItem(THEME_STORAGE_KEY, next);
      }
    } catch (e) {
      logWarning("테마를 저장하지 못했다", e); // 지금 화면에는 적용된다
    }
  }

  return { theme, setTheme: selectTheme };
}
