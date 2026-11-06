// 화면이 서버에 요청하는 계약. 구현은 mockClient.ts(목업) · httpClient.ts(실제 서버)이고, 앱 루트에서 ApiProvider 로 끼운다.

import type { HealthResponse, QueryRequest, QueryResponse, SessionInfo } from "./types";

/**
 * 요청이 응답을 받지 못했거나 거절된 이유. 서버가 status="error" 로 답한 경우는 이 오류가 아니라 QueryResponse 로 온다.
 * - aborted: 사용자가 중지함
 * - network: 서버에 닿지 못함 (연결 실패 · 연결 끊김 · 본문 없는 HTTP 오류. 프록시 5xx = 백엔드 꺼짐)
 * - bad_response: 응답이 계약과 다름
 * - invalid_question · invalid_retrieval_mode · invalid_session_id · invalid_request: 422 (어느 값이 거절됐는지)
 */
export type RequestErrorCode =
  | "aborted"
  | "network"
  | "bad_response"
  | "invalid_question"
  | "invalid_retrieval_mode"
  | "invalid_session_id"
  | "invalid_request";

/** 응답을 받지 못했거나 요청이 거절된 경우의 오류. message 는 로그용 원인이다 */
export class RequestError extends Error {
  readonly code: RequestErrorCode;

  constructor(code: RequestErrorCode, message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "RequestError";
    this.code = code;
  }
}

/** 화면이 서버에 요청하는 것 */
export interface ApiClient {
  /**
   * 서버 상태.
   *
   * @throws RequestError 응답을 받지 못했거나 형식이 계약과 다를 때
   */
  getHealth: (signal?: AbortSignal) => Promise<HealthResponse>;
  /**
   * 질문을 보내 답을 받는다 (status 가 "error" 일 수 있다).
   *
   * @throws RequestError 응답을 받지 못했거나 요청이 422 로 거절됐을 때
   */
  query: (request: QueryRequest, signal?: AbortSignal) => Promise<QueryResponse>;
  /**
   * 세션의 대화 이력 (최근 SESSION_MAX_LIMIT 개까지).
   *
   * @returns 없거나 만료된 세션이면 null
   * @throws RequestError 응답을 받지 못했거나 요청이 422 로 거절됐을 때
   */
  getSession: (sessionId: string, signal?: AbortSignal) => Promise<SessionInfo | null>;
}
