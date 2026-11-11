import { useCallback, useSyncExternalStore } from "react";

import { matchesMedia, watchMedia } from "../lib/media";

/**
 * CSS 미디어 쿼리가 맞는지. 바뀌면 다시 그린다.
 *
 * @param fallback matchMedia 가 없는 환경(테스트)에서 돌려줄 값
 */
export function useMediaQuery(query: string, fallback: boolean): boolean {
  // useSyncExternalStore 는 subscribe 가 바뀌면 다시 구독하므로 query 가 같을 때는 같은 함수를 넘긴다
  const subscribe = useCallback(
    (onStoreChange: () => void) => watchMedia(query, onStoreChange),
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => matchesMedia(query, fallback),
    () => fallback,
  );
}
