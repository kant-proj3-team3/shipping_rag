// 이 파일은 scripts/gen-schemas.mjs 가 contracts/openapi.json 에서 만든다. 손으로 고치지 않는다 (npm run gen:api).
// 서버 형식(snake_case) zod 스키마(*Raw), 화면 타입(camelCase), 서버 → 화면 변환 함수(to*), 화면 → 서버 요청 본문 함수(to*Body),
// 요청 제약 상수(*_MAX_LENGTH · *_PATTERN · *_MAXIMUM).

import { z } from "zod";

import type { components } from "./openapi";

type Schemas = components["schemas"];

/** AnswerStatus 값 목록 */
export const ANSWER_STATUSES = ["answered", "needs_clarification", "abstained", "error"] as const;
/** ANSWER_STATUSES 의 값 하나 */
export type AnswerStatus = (typeof ANSWER_STATUSES)[number];
/** AnswerStatus 검증 */
export const answerStatusSchema = z.enum(ANSWER_STATUSES);

/** status=error 일 때만 쓰는 오류 분류. 근거 부족(abstained)과 섞지 않는다. */
export const ERROR_CODES = [
  "index_not_ready",
  "retrieval_failed",
  "model_timeout",
  "model_failed",
  "output_invalid",
  "ingest_failed",
  "invalid_input",
  "session_not_found",
  "internal",
] as const;
/** ERROR_CODES 의 값 하나 */
export type ErrorCode = (typeof ERROR_CODES)[number];
/** ErrorCode 검증 */
export const errorCodeSchema = z.enum(ERROR_CODES);

/** QueryResponse가 아닌 오류 응답(현재는 /session 404). */
export const apiErrorRaw = z.strictObject({
  error_code: errorCodeSchema,
  message: z.string(),
});

/** QueryResponse가 아닌 오류 응답(현재는 /session 404). */
export interface ApiError {
  errorCode: ErrorCode;
  message: string;
}

/** ApiError 서버 형식 → 화면 형식 */
export function toApiError(raw: z.output<typeof apiErrorRaw>): ApiError {
  return {
    errorCode: raw.error_code,
    message: raw.message,
  };
}

/** 출처 한 건 */
export const citationRaw = z.strictObject({
  source_id: z.string(),
  book_id: z.string(),
  file_name: z.string(),
  page: z.number().int().min(1),
});

/** 출처 한 건 */
export interface Citation {
  /** 요청 안에서만 유효하다. 화면에 보이지 않는다 */
  sourceId: string;
  bookId: string;
  /** 문서명 (예: IS12.pdf) */
  fileName: string;
  /** 쪽 번호 (첫 쪽 = 1) */
  page: number;
}

/** Citation 서버 형식 → 화면 형식 */
export function toCitation(raw: z.output<typeof citationRaw>): Citation {
  return {
    sourceId: raw.source_id,
    bookId: raw.book_id,
    fileName: raw.file_name,
    page: raw.page,
  };
}

/** ValidationError 서버 형식 검증 */
export const validationErrorRaw = z.object({
  loc: z.array(z.union([z.string(), z.number().int()])),
  msg: z.string(),
  type: z.string(),
  input: z.unknown().optional(),
  ctx: z.record(z.string(), z.unknown()).optional(),
});

/** ValidationError 화면 형식 */
export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input: unknown;
  /** 서버가 보내지 않으면 null */
  ctx: Record<string, unknown> | null;
}

/** ValidationError 서버 형식 → 화면 형식 */
export function toValidationError(raw: z.output<typeof validationErrorRaw>): ValidationError {
  return {
    loc: raw.loc,
    msg: raw.msg,
    type: raw.type,
    input: raw.input,
    ctx: raw.ctx ?? null,
  };
}

/** HTTPValidationError 서버 형식 검증 */
export const httpValidationErrorRaw = z.object({
  detail: z.array(validationErrorRaw).optional(),
});

/** HTTPValidationError 화면 형식 */
export interface HTTPValidationError {
  /** 서버가 보내지 않으면 빈 목록 */
  detail: ValidationError[];
}

/** HTTPValidationError 서버 형식 → 화면 형식 */
export function toHTTPValidationError(
  raw: z.output<typeof httpValidationErrorRaw>,
): HTTPValidationError {
  return {
    detail: (raw.detail ?? []).map((item) => toValidationError(item)),
  };
}

/** 세 가지 필수 RAG 검색 방식. */
export const RETRIEVAL_MODES = ["naive", "hybrid", "hybrid_rerank"] as const;
/** RETRIEVAL_MODES 의 값 하나 */
export type RetrievalMode = (typeof RETRIEVAL_MODES)[number];
/** RetrievalMode 검증 */
export const retrievalModeSchema = z.enum(RETRIEVAL_MODES);

/** GET /health 응답 */
export const healthResponseRaw = z.strictObject({
  status: z.literal("ok").default("ok"),
  index_ready: z.boolean(),
  index_name: z.string().nullable().optional(),
  embedder_id: z.string().nullable().optional(),
  supported_modes: z.array(retrievalModeSchema).optional(),
});

/** GET /health 응답 */
export interface HealthResponse {
  status: "ok";
  /** false 면 서버는 떴지만 검색 인덱스가 준비되지 않았다 */
  indexReady: boolean;
  /** 서버가 보내지 않으면 null */
  indexName: string | null;
  /** 서버가 보내지 않으면 null */
  embedderId: string | null;
  /** 서버가 지원하는 검색 방식. 비어 있으면 알려 주지 않은 것 · 서버가 보내지 않으면 빈 목록 */
  supportedModes: RetrievalMode[];
}

/** HealthResponse 서버 형식 → 화면 형식 */
export function toHealthResponse(raw: z.output<typeof healthResponseRaw>): HealthResponse {
  return {
    status: raw.status,
    indexReady: raw.index_ready,
    indexName: raw.index_name ?? null,
    embedderId: raw.embedder_id ?? null,
    supportedModes: raw.supported_modes ?? [],
  };
}

/** 응답 부가 정보. 모르는 값은 0 이 아니라 null 이다 */
export const queryMetaRaw = z.strictObject({
  retrieval_mode: retrievalModeSchema,
  latency_ms: z.number().nullable().optional(),
  input_tokens: z.number().int().nullable().optional(),
  output_tokens: z.number().int().nullable().optional(),
  cost_usd: z.number().nullable().optional(),
  cache_hit: z.boolean().default(false),
  trace_id: z.string().nullable().optional(),
});

/** 응답 부가 정보. 모르는 값은 0 이 아니라 null 이다 */
export interface QueryMeta {
  /** 실제로 쓴 검색 방식 */
  retrievalMode: RetrievalMode;
  /** 서버가 보내지 않으면 null */
  latencyMs: number | null;
  /** 서버가 보내지 않으면 null */
  inputTokens: number | null;
  /** 서버가 보내지 않으면 null */
  outputTokens: number | null;
  /** 서버가 보내지 않으면 null */
  costUsd: number | null;
  /** 캐시에서 꺼낸 응답 */
  cacheHit: boolean;
  /** 서버가 보내지 않으면 null */
  traceId: string | null;
}

/** QueryMeta 서버 형식 → 화면 형식 */
export function toQueryMeta(raw: z.output<typeof queryMetaRaw>): QueryMeta {
  return {
    retrievalMode: raw.retrieval_mode,
    latencyMs: raw.latency_ms ?? null,
    inputTokens: raw.input_tokens ?? null,
    outputTokens: raw.output_tokens ?? null,
    costUsd: raw.cost_usd ?? null,
    cacheHit: raw.cache_hit,
    traceId: raw.trace_id ?? null,
  };
}

/** QueryRequest.question 최대 길이 (계약 maxLength) */
export const QUERY_REQUEST_QUESTION_MAX_LENGTH = 500;

/** QueryRequest.session_id 형식 (계약 pattern) */
export const QUERY_REQUEST_SESSION_ID_PATTERN = new RegExp("^[A-Za-z0-9_-]{8,128}$");

/** QueryRequest 화면 형식 (요청). 선택 여부는 계약 그대로다 */
export interface QueryRequestInput {
  /** 질문 원문 (공백만은 안 된다) */
  question: string;
  retrievalMode?: RetrievalMode | null;
  /** 대화 세션 id. 같은 대화의 질문은 같은 id 로 보낸다 */
  sessionId?: string | null;
}

/** QueryRequest 화면 형식 → 서버 형식 요청 본문 */
export function toQueryRequestBody(request: QueryRequestInput): Schemas["QueryRequest"] {
  return {
    question: request.question,
    retrieval_mode: request.retrievalMode,
    session_id: request.sessionId,
  };
}

/** POST /query 응답. 오류 상태 코드(status=error)도 이 모양이다 */
export const queryResponseRaw = z.strictObject({
  request_id: z.string(),
  status: answerStatusSchema,
  answer: z.string(),
  reason: z.string(),
  citations: z.array(citationRaw).optional(),
  error_code: errorCodeSchema.nullable().optional(),
  meta: queryMetaRaw,
});

/** POST /query 응답. 오류 상태 코드(status=error)도 이 모양이다 */
export interface QueryResponse {
  requestId: string;
  status: AnswerStatus;
  /** 결론. needs_clarification 이면 되묻는 문장, abstained 면 보류 이유, error 면 서버의 사용자용 문구 */
  answer: string;
  /** 근거 */
  reason: string;
  /** answered 면 1개 이상 · 서버가 보내지 않으면 빈 목록 */
  citations: Citation[];
  /** status=error 일 때만, 그리고 반드시 있다. 로그용이며 화면에 보이지 않는다 · 서버가 보내지 않으면 null */
  errorCode: ErrorCode | null;
  meta: QueryMeta;
}

/** QueryResponse 서버 형식 → 화면 형식 */
export function toQueryResponse(raw: z.output<typeof queryResponseRaw>): QueryResponse {
  return {
    requestId: raw.request_id,
    status: raw.status,
    answer: raw.answer,
    reason: raw.reason,
    citations: (raw.citations ?? []).map((item) => toCitation(item)),
    errorCode: raw.error_code ?? null,
    meta: toQueryMeta(raw.meta),
  };
}

/** 세션에 기록된 질의응답 한 번. status=error 응답은 기록하지 않는다. */
export const sessionTurnRaw = z.strictObject({
  request_id: z.string(),
  asked_at: z.iso.datetime({ offset: true }),
  question: z.string(),
  retrieval_mode: retrievalModeSchema,
  status: answerStatusSchema,
  answer: z.string(),
  citations: z.array(citationRaw).optional(),
});

/** 세션에 기록된 질의응답 한 번. status=error 응답은 기록하지 않는다. */
export interface SessionTurn {
  requestId: string;
  /** 질문한 시각 · ms 시각 (서버의 date-time 을 바꾼 값) */
  askedAt: number;
  question: string;
  retrievalMode: RetrievalMode;
  status: AnswerStatus;
  answer: string;
  /** 서버가 보내지 않으면 빈 목록 */
  citations: Citation[];
}

/** SessionTurn 서버 형식 → 화면 형식 */
export function toSessionTurn(raw: z.output<typeof sessionTurnRaw>): SessionTurn {
  return {
    requestId: raw.request_id,
    askedAt: Date.parse(raw.asked_at),
    question: raw.question,
    retrievalMode: raw.retrieval_mode,
    status: raw.status,
    answer: raw.answer,
    citations: (raw.citations ?? []).map((item) => toCitation(item)),
  };
}

/** GET /session/{session_id} 응답. */
export const sessionInfoRaw = z.strictObject({
  session_id: z.string(),
  created_at: z.iso.datetime({ offset: true }),
  last_active_at: z.iso.datetime({ offset: true }),
  expires_at: z.iso.datetime({ offset: true }).nullable().optional(),
  turn_count: z.number().int().min(0),
  turns: z.array(sessionTurnRaw).optional(),
});

/** GET /session/{session_id} 응답. */
export interface SessionInfo {
  sessionId: string;
  /** ms 시각 (서버의 date-time 을 바꾼 값) */
  createdAt: number;
  /** ms 시각 (서버의 date-time 을 바꾼 값) */
  lastActiveAt: number;
  /** 만료 예정 시각 · ms 시각 (서버의 date-time 을 바꾼 값) · 서버가 보내지 않으면 null */
  expiresAt: number | null;
  /** 세션 전체 turn 수. turns 는 그중 최근 일부일 수 있다 */
  turnCount: number;
  /** 오래된 것 → 최신 순 · 서버가 보내지 않으면 빈 목록 */
  turns: SessionTurn[];
}

/** SessionInfo 서버 형식 → 화면 형식 */
export function toSessionInfo(raw: z.output<typeof sessionInfoRaw>): SessionInfo {
  return {
    sessionId: raw.session_id,
    createdAt: Date.parse(raw.created_at),
    lastActiveAt: Date.parse(raw.last_active_at),
    expiresAt: raw.expires_at == null ? null : Date.parse(raw.expires_at),
    turnCount: raw.turn_count,
    turns: (raw.turns ?? []).map((item) => toSessionTurn(item)),
  };
}

/** /session/{session_id} 의 limit 최댓값 (계약 maximum) */
export const SESSION_LIMIT_MAXIMUM = 100;

// 생성한 스키마가 openapi-typescript 의 타입(openapi.d.ts)과 같은지 컴파일 때 확인한다 (생성 스크립트의 실수를 잡는다)
type Mutual<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
type Same<A, B> = Mutual<A, B> extends true ? Mutual<keyof A, keyof B> : false;
type Expect<T extends true> = T;
/** 생성 결과 확인용 (값으로 쓰지 않는다) */
export type GeneratedMatchesContract = [
  Expect<Same<AnswerStatus, Schemas["AnswerStatus"]>>,
  Expect<Same<ErrorCode, Schemas["ErrorCode"]>>,
  Expect<Same<z.output<typeof apiErrorRaw>, Schemas["ApiError"]>>,
  Expect<Same<z.output<typeof citationRaw>, Schemas["Citation"]>>,
  Expect<Same<z.output<typeof validationErrorRaw>, Schemas["ValidationError"]>>,
  Expect<Same<z.output<typeof httpValidationErrorRaw>, Schemas["HTTPValidationError"]>>,
  Expect<Same<RetrievalMode, Schemas["RetrievalMode"]>>,
  Expect<Same<z.output<typeof healthResponseRaw>, Schemas["HealthResponse"]>>,
  Expect<Same<z.output<typeof queryMetaRaw>, Schemas["QueryMeta"]>>,
  Expect<Same<z.output<typeof queryResponseRaw>, Schemas["QueryResponse"]>>,
  Expect<Same<z.output<typeof sessionTurnRaw>, Schemas["SessionTurn"]>>,
  Expect<Same<z.output<typeof sessionInfoRaw>, Schemas["SessionInfo"]>>,
];
