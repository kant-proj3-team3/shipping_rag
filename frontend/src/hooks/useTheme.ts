import { useCallback, useEffect, useState } from "react";

import { useMediaQuery } from "./useMediaQuery";
import { useStorage } from "./useStorage";
import { useStorageChange } from "./useStorageChange";
import { THEME_STORAGE_KEY } from "../lib/config";
import { THEMES, type Theme } from "../lib/labels";
import { readItem, writeItem, type KeyValueStorage } from "../lib/storage";

/** useTheme 이 돌려주는 선택값과 변경 함수 */
export interface UseThemeResult {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

function readTheme(storage: KeyValueStorage): Theme {
  const value = readItem(storage, THEME_STORAGE_KEY, "테마");
  return THEMES.find((t) => t !== "system" && t === value) ?? "system";
}

/**
 * 화면 테마 (시스템 · 라이트 · 다크). 고른 값은 저장소에 남기고, 다른 탭에서 바꾸면 따라 바꾼다.
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

  // 다른 탭이 테마를 바꾸면 따라 바꾼다
  const followOtherTab = useCallback(() => setTheme(readTheme(storage)), [storage]);
  useStorageChange(THEME_STORAGE_KEY, followOtherTab);

  function selectTheme(next: Theme): void {
    setTheme(next);
    // "시스템"은 저장하지 않는다 (지운다). 못 써도 지금 화면에는 적용된다
    writeItem(storage, THEME_STORAGE_KEY, next === "system" ? undefined : next, "테마");
  }

  return { theme, setTheme: selectTheme };
}
