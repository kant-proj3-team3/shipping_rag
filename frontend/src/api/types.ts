// 화면 안에서 쓰는 API 데이터 형식 (camelCase).
// 계약 모양(타입 · 값 목록 · 요청 제약 · 설명)은 contracts/openapi.json 에서 생성한 generated/schemas.generated.ts 가 원본이다
// (npm run gen:api. 계약에 없는 설명은 scripts/schema-descriptions.mjs). 여기에는 openapi.json 에 없는 계약 값과 화면 쪽 약속만 둔다.

import {
  QUERY_REQUEST_SESSION_ID_PATTERN,
  type ErrorCode,
  type QueryRequestInput,
} from "./generated/schemas.generated";

export {
  ANSWER_STATUSES,
  ERROR_CODES,
  QUERY_REQUEST_QUESTION_MAX_LENGTH,
  RETRIEVAL_MODES,
} from "./generated/schemas.generated";
export type {
  AnswerStatus,
  Citation,
  ErrorCode,
  HealthResponse,
  QueryMeta,
  QueryResponse,
  RetrievalMode,
  SessionInfo,
  SessionTurn,
} from "./generated/schemas.generated";

/**
 * status="error" 응답의 error_code → HTTP 상태. 정상 처리된 세 상태는 모두 200 이다.
 * 원본은 packages/common/src/common/api.py 의 ERROR_HTTP_STATUS 다 (openapi.json 에는 나오지 않아 옮겨 적었다).
 */
export const ERROR_HTTP_STATUS: Readonly<Partial<Record<ErrorCode, number>>> = {
  invalid_input: 400,
  index_not_ready: 503,
  retrieval_failed: 502,
  model_timeout: 504,
  model_failed: 502,
  output_invalid: 502,
  internal: 500,
};

/** GET /session 이 한 번에 돌려주는 최근 turn 최대 개수 (계약 SESSION_MAX_LIMIT. openapi.json 에 나오지 않아 옮겨 적었다) */
export const SESSION_MAX_LIMIT = 100;

/** 세션 id 형식 (계약 QueryRequest.session_id 의 pattern). 어기면 서버가 422 로 거절한다 */
export const SESSION_ID_PATTERN = QUERY_REQUEST_SESSION_ID_PATTERN;

/** POST /query 요청. 계약에서는 검색 방식 · 세션 id 가 선택이지만 화면은 항상 보낸다 */
export type QueryRequest = {
  [K in keyof QueryRequestInput]-?: NonNullable<QueryRequestInput[K]>;
};
