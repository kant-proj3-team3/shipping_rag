// 실제 서버(개발 중에는 서버 목업 api)에 요청하는 ApiClient. 응답 해석은 responses.ts 가 한다.

import { RequestError, type ApiClient } from "./client";
import type { paths } from "./generated/openapi";
import { readHealth, readQueryResponse, readSessionInfo, type HttpResult } from "./responses";
import { toQueryBody } from "./schemas";
import {
  SESSION_MAX_LIMIT,
  type HealthResponse,
  type QueryRequest,
  type QueryResponse,
  type SessionInfo,
} from "./types";

// 경로는 계약 생성 타입(paths)의 키로 적는다. 계약에서 경로가 바뀌면 이 자리에서 타입 오류가 난다
const PATH_HEALTH: keyof paths = "/health";
const PATH_QUERY: keyof paths = "/query";
const PATH_SESSION: keyof paths = "/session/{session_id}";

/** 실제 서버 클라이언트 설정 */
export interface HttpApiClientOptions {
  /** API 주소. 빈 문자열이면 같은 주소의 상대 경로(개발 중에는 Vite 프록시)로 보낸다 */
  baseUrl: string;
  /** /health 응답 대기 한도 (ms). 넘으면 network 오류 */
  healthTimeoutMs: number;
}

/** RAG Q&A API 서버(/health · /query · /session)에 붙는 클라이언트 */
export function createHttpApiClient({ baseUrl, healthTimeoutMs }: HttpApiClientOptions): ApiClient {
  const root = baseUrl.replace(/\/+$/, "");

  async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
    const timeout = AbortSignal.timeout(healthTimeoutMs);
    const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;
    return readHealth(await send(`${root}${PATH_HEALTH}`, { signal: combined }, signal));
  }

  async function query(request: QueryRequest, signal?: AbortSignal): Promise<QueryResponse> {
    const init: RequestInit = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toQueryBody(request)),
      signal,
    };
    return readQueryResponse(await send(`${root}${PATH_QUERY}`, init, signal));
  }

  async function getSession(sessionId: string, signal?: AbortSignal): Promise<SessionInfo | null> {
    const path = PATH_SESSION.replace("{session_id}", encodeURIComponent(sessionId));
    const url = `${root}${path}?limit=${SESSION_MAX_LIMIT}`;
    return readSessionInfo(await send(url, { signal }, signal));
  }

  return { getHealth, query, getSession };
}

/**
 * 요청을 보내 HTTP 상태와 JSON 본문을 받는다. 본문이 JSON 이 아니면 body 는 undefined 다.
 *
 * @param callerSignal 호출자가 넘긴 중지 신호. 이것으로 끊겼을 때만 aborted, 그 밖(연결 실패 · 시간 초과)은 network
 * @throws RequestError 응답을 받지 못했을 때
 */
async function send(
  url: string,
  init: RequestInit,
  callerSignal: AbortSignal | undefined,
): Promise<HttpResult> {
  try {
    const res = await fetch(url, init);
    return { status: res.status, body: parseJson(await res.text()) };
  } catch (e) {
    if (callerSignal?.aborted) {
      throw new RequestError("aborted", "중지되었습니다", { cause: e });
    }
    throw new RequestError("network", `서버에 연결하지 못했습니다 (${url})`, { cause: e });
  }
}

function parseJson(text: string): unknown {
  try {
    const value: unknown = JSON.parse(text);
    return value;
  } catch {
    return undefined; // JSON 이 아니다 (빈 본문 · 프록시 오류 페이지). responses.ts 가 HTTP 상태로 판단한다
  }
}
