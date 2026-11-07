import { useEffect, useState } from "react";

/** 기본 갱신 주기. 날짜 묶음 · 시각 표시는 분 단위라 1분이면 충분하다 */
const DEFAULT_INTERVAL_MS = 60_000;

/** 현재 시각(ms). intervalMs 마다 갱신한다 (자정이 지나면 "오늘 · 어제" 묶음이 바뀌도록) */
export function useNow(intervalMs = DEFAULT_INTERVAL_MS): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}
