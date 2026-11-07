// CSS 미디어 쿼리 확인 · 구독. matchMedia 가 없는 환경(테스트)에서도 안전하게 부른다.

function hasMatchMedia(): boolean {
  return typeof window.matchMedia === "function";
}

function noop(): void {
  // 구독할 것이 없다
}

/** 미디어 쿼리가 지금 맞는지. matchMedia 가 없으면 fallback */
export function matchesMedia(query: string, fallback: boolean): boolean {
  return hasMatchMedia() ? window.matchMedia(query).matches : fallback;
}

/**
 * 미디어 쿼리가 바뀔 때마다 onChange(맞는지)를 부른다. matchMedia 가 없으면 아무것도 하지 않는다.
 *
 * @returns 구독을 끝내는 함수
 */
export function watchMedia(query: string, onChange: (matches: boolean) => void): () => void {
  if (!hasMatchMedia()) {
    return noop;
  }
  const media = window.matchMedia(query);
  const handleChange = (e: MediaQueryListEvent): void => onChange(e.matches);
  media.addEventListener("change", handleChange);
  return () => media.removeEventListener("change", handleChange);
}
