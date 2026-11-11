import { useEffect, useRef, useState } from "react";

import { PENDING_MIN_VISIBLE_MS, PENDING_SHOW_DELAY_MS } from "../lib/config";

/**
 * 답변 대기 표시를 보여 줄지. 기다림이 짧으면 번쩍이지 않게 하고, 한번 보이면 바로 사라지지 않게 한다.
 * - 기다리기 시작해 PENDING_SHOW_DELAY_MS 가 지나야 true 가 된다. 그 전에 끝나면 true 가 되지 않는다
 * - true 가 된 뒤 기다림이 끝나도 PENDING_MIN_VISIBLE_MS 를 채울 때까지 true 로 남는다
 *
 * @param isPending 지금 답을 기다리는 중인지
 */
export function usePendingIndicator(isPending: boolean): boolean {
  const [isVisible, setIsVisible] = useState(false);
  // 표시를 켠 시각 (ms). 최소 표시 시간을 재는 데만 쓴다
  const shownAtRef = useRef(0);

  // 시간이 지나야 바뀌는 값이라 타이머로 맞춘다
  useEffect(() => {
    if (isPending && !isVisible) {
      const timer = setTimeout(() => {
        shownAtRef.current = Date.now();
        setIsVisible(true);
      }, PENDING_SHOW_DELAY_MS);
      return () => clearTimeout(timer);
    }
    if (!isPending && isVisible) {
      const remaining = PENDING_MIN_VISIBLE_MS - (Date.now() - shownAtRef.current);
      const timer = setTimeout(() => setIsVisible(false), Math.max(0, remaining));
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [isPending, isVisible]);

  return isVisible;
}
