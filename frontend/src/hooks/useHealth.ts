import { useEffect, useState } from "react";

import { useApi } from "./useApi";
import type { HealthResponse } from "../api/types";
import { HEALTH_INTERVAL_MS } from "../lib/config";

/** 서버 상태 확인 결과 */
export type HealthState =
  | { kind: "checking" }
  | { kind: "ok"; health: HealthResponse }
  /** 서버는 떴지만 검색 인덱스가 준비되지 않음 (index_ready=false) */
  | { kind: "index_not_ready"; health: HealthResponse }
  | { kind: "offline" };

/** /health 를 주기적으로 확인한다. 탭이 숨겨진 동안은 쉬고, 다시 보이면 바로 확인한다 */
export function useHealth(): HealthState {
  const api = useApi();
  const [health, setHealth] = useState<HealthState>({ kind: "checking" });

  useEffect(() => {
    const controller = new AbortController();

    async function check(): Promise<void> {
      try {
        const result = await api.getHealth(controller.signal);
        setHealth({ kind: result.indexReady ? "ok" : "index_not_ready", health: result });
      } catch {
        if (!controller.signal.aborted) {
          setHealth({ kind: "offline" }); // 원인은 httpClient 의 RequestError 에 있고, 화면에는 "연결 안 됨"만 보인다
        }
      }
    }
    const checkNow = (): void => void check();

    function handleVisibilityChange(): void {
      if (document.visibilityState === "visible") {
        checkNow();
      }
    }

    // 숨긴 탭에서는 주기 확인을 건너뛴다. 다시 보이면 visibilitychange 에서 바로 확인한다
    function checkIfVisible(): void {
      if (document.visibilityState !== "hidden") {
        checkNow();
      }
    }

    checkNow();
    const timer = setInterval(checkIfVisible, HEALTH_INTERVAL_MS);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      controller.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [api]);

  return health;
}
