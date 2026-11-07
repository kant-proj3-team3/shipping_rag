import { skipToken, useQuery } from "@tanstack/react-query";

import { useApi } from "./useApi";
import type { ApiClient } from "../api/client";
import type { SessionInfo } from "../api/types";
import { logWarning } from "../lib/logger";
import type { SessionLookup } from "../lib/session";

// 실패는 로그만 남기고 그대로 던진다. 화면은 브라우저에 남은 내용으로 이어 간다 (lib/session.ts)
async function getSessionOrWarn(
  api: ApiClient,
  id: string,
  signal: AbortSignal,
): Promise<SessionInfo | null> {
  try {
    return await api.getSession(id, signal);
  } catch (e) {
    if (!signal.aborted) {
      logWarning("대화 세션을 확인하지 못했다", e);
    }
    throw e;
  }
}

/**
 * 대화의 서버 세션을 확인한다 (GET /session). id 가 없으면 확인하지 않는다.
 * 결과는 그 대화를 보는 동안만 들고 있어, 다른 대화를 봤다가 다시 열면 다시 확인한다
 */
export function useSessionLookup(id: string | undefined): SessionLookup {
  const api = useApi();
  const query = useQuery({
    queryKey: ["session", id],
    queryFn: id === undefined ? skipToken : ({ signal }) => getSessionOrWarn(api, id, signal),
    retry: false,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    // 브라우저가 오프라인이라고 해도 멈추지 않고 실패로 끝낸다 (멈추면 확인 중에서 벗어나지 못한다)
    networkMode: "always",
  });

  if (id === undefined) {
    return { state: "skipped" };
  }
  if (query.isPending) {
    return { state: "pending" };
  }
  if (query.isError) {
    return { state: "failed" };
  }
  return { state: "done", info: query.data };
}
