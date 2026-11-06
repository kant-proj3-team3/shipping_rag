// 화면 안에서 쓰는 API 데이터 형식 (camelCase).
// 서버 형식(snake_case)의 원본은 contracts/openapi.json 에서 생성한 generated/openapi.d.ts 다.
// 서버 응답은 schemas.ts 가 검증해 이 형식으로 바꾼다.

import type { components } from "./generated/openapi";

type Schemas = components["schemas"];

/**
 * 값 목록이 계약의 유니온 타입(T)과 같은 값을 모두 담을 때만 통과한다.
 * 계약에 값이 추가되면 목록에 빠진 값 때문에 이 자리에서 타입 오류가 난다.
 */
function listOf<T extends string>() {
  return <const L extends readonly T[]>(list: L & ([T] extends [L[number]] ? unknown : never)): L =>
    list;
}

/** 검색 방식 (RetrievalMode) */
export const RETRIEVAL_MODES = listOf<Schemas["RetrievalMode"]>()([
  "naive",
  "hybrid",
  "hybrid_rerank",
]);
/** RETRIEVAL_MODES 의 값 하나 */
export type RetrievalMode = (typeof RETRIEVAL_MODES)[number];

/** 답변 상태 (AnswerStatus) */
export const ANSWER_STATUSES = listOf<Schemas["AnswerStatus"]>()([
  "answered",
  "needs_clarification",
  "abstained",
  "error",
]);
/** ANSWER_STATUSES 의 값 하나 */
export type AnswerStatus = (typeof ANSWER_STATUSES)[number];

/** 오류 분류 (ErrorCode). 로그용이며 화면에는 사용자용 문구만 보인다 */
export const ERROR_CODES = listOf<Schemas["ErrorCode"]>()([
  "index_not_ready",
  "retrieval_failed",
  "model_timeout",
  "model_failed",
  "output_invalid",
  "ingest_failed",
  "invalid_input",
  "session_not_found",
  "internal",
]);
/** ERROR_CODES 의 값 하나 */
export type ErrorCode = (typeof ERROR_CODES)[number];

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

/** GET /session 이 한 번에 돌려주는 최근 turn 최대 개수 (계약 SESSION_MAX_LIMIT) */
export const SESSION_MAX_LIMIT = 100;

/** 세션 id 형식 (계약 SESSION_ID_PATTERN). 어기면 서버가 422 로 거절한다 */
export const SESSION_ID_PATTERN = /^[A-Za-z0-9_-]{8,128}$/;

/** GET /health (HealthResponse) */
export interface HealthResponse {
  status: "ok";
  /** false 면 서버는 떴지만 검색 인덱스가 준비되지 않았다 */
  indexReady: boolean;
  indexName: string | null;
  embedderId: string | null;
  /** 서버가 지원하는 검색 방식. 비어 있으면 알려 주지 않은 것 */
  supportedModes: RetrievalMode[];
}

/** 출처 한 건 (Citation). sourceId 는 요청 안에서만 유효하고 화면에 보이지 않는다 */
export interface Citation {
  sourceId: string;
  bookId: string;
  /** 문서명 (예: IS12.pdf) */
  fileName: string;
  /** 쪽 번호 (첫 쪽 = 1) */
  page: number;
}

/** 응답 부가 정보 (QueryMeta). 모르는 값은 null 이다 (0 이 아니다) */
export interface QueryMeta {
  /** 실제로 쓴 검색 방식 */
  retrievalMode: RetrievalMode;
  latencyMs: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  costUsd: number | null;
  /** 캐시에서 꺼낸 응답 */
  cacheHit: boolean;
  traceId: string | null;
}

/** POST /query 응답 (QueryResponse) */
export interface QueryResponse {
  requestId: string;
  status: AnswerStatus;
  /** 결론. needs_clarification 이면 되묻는 문장, abstained 면 보류 이유, error 면 서버의 사용자용 문구 */
  answer: string;
  /** 근거 */
  reason: string;
  /** answered 면 1개 이상 */
  citations: Citation[];
  /** status 가 "error" 일 때만, 그리고 반드시 있다 */
  errorCode: ErrorCode | null;
  meta: QueryMeta;
}

/** POST /query 요청 (QueryRequest). 계약에서는 검색 방식 · 세션 id 가 선택이지만 화면은 항상 보낸다 */
export interface QueryRequest {
  /** 질문 원문 (1~MAX_QUESTION_LENGTH 자, 공백만은 안 됨) */
  question: string;
  retrievalMode: RetrievalMode;
  /** 대화 세션 id (영문 · 숫자 · _ · - 8~128자). 같은 대화의 질문은 같은 id 로 보낸다 */
  sessionId: string;
}

/** 세션에 기록된 질의응답 한 번 (SessionTurn). status="error" 응답은 기록되지 않는다 */
export interface SessionTurn {
  requestId: string;
  /** 질문한 시각 (ms) */
  askedAt: number;
  question: string;
  retrievalMode: RetrievalMode;
  status: AnswerStatus;
  answer: string;
  citations: Citation[];
}

/** GET /session/{session_id} 응답 (SessionInfo) */
export interface SessionInfo {
  sessionId: string;
  /** 시각은 모두 ms */
  createdAt: number;
  lastActiveAt: number;
  /** 만료 예정 시각. 서버가 알려 주지 않으면 null */
  expiresAt: number | null;
  /** 세션 전체 turn 수. turns 는 그중 최근 일부일 수 있다 */
  turnCount: number;
  /** 오래된 것 → 최신 순 */
  turns: SessionTurn[];
}
