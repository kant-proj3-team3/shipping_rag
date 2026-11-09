// 화면 안에서 쓰는 API 데이터 형식 (camelCase).
// 계약 모양(타입 · 값 목록 · 요청 제약 · 설명)은 contracts/openapi.json 에서 생성한 generated/schemas.generated.ts 가 원본이다
// (npm run gen:api. 계약에 없는 설명은 scripts/schema-descriptions.mjs). 여기에는 화면 쪽 이름과 약속만 둔다.

import {
  QUERY_REQUEST_SESSION_ID_PATTERN,
  SESSION_LIMIT_MAXIMUM,
  type QueryRequestInput,
} from "./generated/schemas.generated";

export {
  ANSWER_STATUSES,
  QUERY_REQUEST_QUESTION_MAX_LENGTH,
  RETRIEVAL_MODES,
} from "./generated/schemas.generated";
export type {
  AnswerStatus,
  Citation,
  HealthResponse,
  QueryResponse,
  RetrievalMode,
  SessionInfo,
  SessionTurn,
} from "./generated/schemas.generated";

/** GET /session 이 한 번에 돌려주는 최근 turn 최대 개수 (계약 SESSION_MAX_LIMIT. openapi.json 의 limit 최댓값에서 생성한다) */
export const SESSION_MAX_LIMIT = SESSION_LIMIT_MAXIMUM;

/** 세션 id 형식 (계약 QueryRequest.session_id 의 pattern). 어기면 서버가 422 로 거절한다 */
export const SESSION_ID_PATTERN = QUERY_REQUEST_SESSION_ID_PATTERN;

/** POST /query 요청. 계약에서는 검색 방식 · 세션 id 가 선택이지만 화면은 항상 보낸다 */
export type QueryRequest = {
  [K in keyof QueryRequestInput]-?: NonNullable<QueryRequestInput[K]>;
};
