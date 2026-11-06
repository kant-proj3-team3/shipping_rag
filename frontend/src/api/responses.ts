// 서버 응답(HTTP 상태 + 본문)을 화면 형식으로 읽는다. 실제 서버(httpClient)와 목업(mockClient)이 같은 함수로 읽는다.
// 본문은 JSON 으로 읽은 값이다. JSON 이 아니면(프록시 오류 페이지 · 빈 본문) undefined 를 넘긴다.

import { RequestError, type RequestErrorCode } from "./client";
import {
  apiErrorSchema,
  healthSchema,
  queryResponseSchema,
  sessionInfoSchema,
  validationErrorSchema,
} from "./schemas";
import {
  ERROR_HTTP_STATUS,
  type HealthResponse,
  type QueryResponse,
  type SessionInfo,
} from "./types";

const HTTP_OK = 200;
const HTTP_NOT_FOUND = 404; // 계약 HTTP_SESSION_NOT_FOUND
const HTTP_UNPROCESSABLE = 422; // FastAPI 요청 검증 실패

/** 422 본문의 거절된 필드 → 오류 코드. 목록에 없는 필드(limit 등)는 invalid_request */
const REJECTED_FIELD_CODES: Readonly<Record<string, RequestErrorCode>> = {
  question: "invalid_question",
  retrieval_mode: "invalid_retrieval_mode",
  session_id: "invalid_session_id",
};

/** 받은 HTTP 응답 */
export interface HttpResult {
  status: number;
  /** JSON 으로 읽은 본문. JSON 이 아니면 undefined */
  body: unknown;
}

/**
 * GET /health 응답을 읽는다.
 *
 * @throws RequestError 200 이 아니거나(network · bad_response) 형식이 계약과 다를 때(bad_response)
 */
export function readHealth({ status, body }: HttpResult): HealthResponse {
  if (status !== HTTP_OK) {
    throw unreachable(status, body, "서버 상태");
  }
  const parsed = healthSchema.safeParse(body);
  if (!parsed.success) {
    throw new RequestError("bad_response", "서버 상태 응답이 계약과 다릅니다", {
      cause: parsed.error,
    });
  }
  return parsed.data;
}

/**
 * POST /query 응답을 읽는다. 서버가 status="error" 로 답했으면(400 · 5xx + 본문) 그대로 돌려준다.
 *
 * @throws RequestError 422 거절, 서버에 닿지 못함(network), 본문 · HTTP 상태가 계약과 다름(bad_response)
 */
export function readQueryResponse({ status, body }: HttpResult): QueryResponse {
  if (status === HTTP_UNPROCESSABLE) {
    throw rejected(body);
  }
  const parsed = queryResponseSchema.safeParse(body);
  if (!parsed.success) {
    if (status !== HTTP_OK) {
      throw unreachable(status, body, "질문 응답");
    }
    throw new RequestError("bad_response", "질문 응답이 계약과 다릅니다", { cause: parsed.error });
  }
  const response = parsed.data;
  const expected = expectedHttpStatus(response);
  if (status !== expected) {
    throw new RequestError(
      "bad_response",
      `응답 상태 ${response.status}(${response.errorCode ?? "-"})는 HTTP ${expected ?? "?"} 여야 하는데 ${status} 로 왔습니다`,
    );
  }
  return response;
}

/**
 * GET /session/{session_id} 응답을 읽는다.
 *
 * @returns 없거나 만료된 세션(404 + session_not_found)이면 null
 * @throws RequestError 422 거절, 서버에 닿지 못함(network), 형식이 계약과 다름(bad_response)
 */
export function readSessionInfo({ status, body }: HttpResult): SessionInfo | null {
  if (status === HTTP_UNPROCESSABLE) {
    throw rejected(body);
  }
  if (
    status === HTTP_NOT_FOUND &&
    apiErrorSchema.safeParse(body).data?.error_code === "session_not_found"
  ) {
    return null;
  }
  if (status !== HTTP_OK) {
    throw unreachable(status, body, "대화 이력");
  }
  const parsed = sessionInfoSchema.safeParse(body);
  if (!parsed.success) {
    throw new RequestError("bad_response", "대화 이력 응답이 계약과 다릅니다", {
      cause: parsed.error,
    });
  }
  return parsed.data;
}

/** 계약이 정한 HTTP 상태. 오류 코드가 매핑에 없으면(ingest_failed 등) undefined → 계약 위반 */
function expectedHttpStatus(response: QueryResponse): number | undefined {
  if (response.status !== "error") {
    return HTTP_OK;
  }
  return response.errorCode === null ? undefined : ERROR_HTTP_STATUS[response.errorCode];
}

/** 기대한 본문을 받지 못함: 본문이 없으면 서버에 닿지 못한 것(network), 다른 JSON 이면 계약 위반(bad_response) */
function unreachable(status: number, body: unknown, what: string): RequestError {
  return body === undefined
    ? new RequestError("network", `${what}을(를) 받지 못했습니다 (HTTP ${status}, 본문 없음)`)
    : new RequestError("bad_response", `${what} 응답이 계약과 다릅니다 (HTTP ${status})`);
}

/** 422 본문에서 거절된 필드를 찾아 오류 코드로 바꾼다 */
function rejected(body: unknown): RequestError {
  const parsed = validationErrorSchema.safeParse(body);
  const fields = parsed.success ? parsed.data.detail.map((d) => String(d.loc.at(-1))) : [];
  const code =
    fields.map((field) => REJECTED_FIELD_CODES[field]).find((c) => c !== undefined) ??
    "invalid_request";
  return new RequestError(code, `요청이 검증에서 거절되었습니다 (HTTP 422: ${fields.join(", ")})`);
}
