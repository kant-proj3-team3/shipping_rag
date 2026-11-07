import { useQuery } from "@tanstack/react-query";

import { useApi } from "./useApi";
import type { HealthResponse } from "../api/types";
import { HEALTH_INTERVAL_MS } from "../lib/config";

/** 서버 상태 질의 키 */
const HEALTH_QUERY_KEY = ["health"] as const;

/** 서버 상태 확인 결과 */
export type HealthState =
  | { kind: "checking" }
  | { kind: "ok"; health: HealthResponse }
  /** 서버는 떴지만 검색 인덱스가 준비되지 않음 (index_ready=false) */
  | { kind: "index_not_ready"; health: HealthResponse }
  | { kind: "offline" };

/**
 * /health 를 HEALTH_INTERVAL_MS 마다 확인한다.
 * 탭이 숨겨진 동안은 쉬고(refetchIntervalInBackground 기본값), 다시 보이면 바로 확인한다(refetchOnWindowFocus)
 */
export function useHealth(): HealthState {
  const api = useApi();
  const query = useQuery({
    queryKey: HEALTH_QUERY_KEY,
    queryFn: ({ signal }) => api.getHealth(signal),
    refetchInterval: HEALTH_INTERVAL_MS,
    refetchOnWindowFocus: true,
    // 연결 실패는 바로 "연결 안 됨"으로 보인다. 다음 주기에 다시 확인한다
    retry: false,
    // 브라우저가 오프라인이라고 해도 요청을 멈추지 않는다 (멈추면 "서버 정상"이 그대로 남는다)
    networkMode: "always",
  });

  if (query.isPending) {
    return { kind: "checking" };
  }
  if (query.isError) {
    // 원인은 httpClient 의 RequestError 에 있고, 화면에는 "연결 안 됨"만 보인다
    return { kind: "offline" };
  }
  return { kind: query.data.indexReady ? "ok" : "index_not_ready", health: query.data };
}
