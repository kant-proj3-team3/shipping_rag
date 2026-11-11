import { useEffect } from "react";

/**
 * 다른 탭이 저장소의 key 값을 바꾸면 onChange 를 부른다. 다른 탭이 저장소를 통째로 비운 때(key 가 null)도 부른다.
 * 같은 탭에서 쓴 값에는 부르지 않는다 (브라우저가 storage 이벤트를 다른 탭에만 보낸다).
 *
 * @param onChange 바뀌면 다시 구독하므로 고정해서 넘긴다 (useCallback)
 */
export function useStorageChange(key: string, onChange: () => void): void {
  useEffect(() => {
    function handleStorage(e: StorageEvent): void {
      if (e.key === key || e.key === null) {
        onChange();
      }
    }
    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, [key, onChange]);
}
