import { skipToken, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

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

function lookupOf(
  isSkipped: boolean,
  isPending: boolean,
  isError: boolean,
  info: SessionInfo | null | undefined,
): SessionLookup {
  if (isSkipped) {
    return { state: "skipped" };
  }
  if (isPending) {
    return { state: "pending" };
  }
  return isError || info === undefined ? { state: "failed" } : { state: "done", info };
}

/**
 * 대화의 서버 세션을 확인한다 (GET /session). id 가 없으면 확인하지 않는다.
 * 결과는 그 대화를 보는 동안만 들고 있어, 다른 대화를 봤다가 다시 열면 다시 확인한다.
 * 같은 결과면 같은 객체를 돌려준다 (이 값으로 만드는 복원 대화를 렌더마다 새로 만들지 않게)
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

  const isSkipped = id === undefined;
  const { isPending, isError, data } = query;
  return useMemo(
    () => lookupOf(isSkipped, isPending, isError, data),
    [isSkipped, isPending, isError, data],
  );
}
