// 서버 형식(snake_case) 검증 · 변환. 서버 형식이 바뀌면 이 파일만 고친다.
// 서버 형식 스키마는 계약 생성 타입(generated/openapi.d.ts)과 모양이 같아야 하고, 화면 타입(types.ts)의 키는 계약 키를
// camelCase 로 바꾼 것과 같아야 한다. 다르면 matching() 자리에서 타입 오류가 난다.
// openapi.json 에 나오지 않는 계약 불변식(packages/common 의 validator)은 superRefine 으로 옮겼다.

import { z } from "zod";

import type { components } from "./generated/openapi";
import {
  ANSWER_STATUSES,
  ERROR_CODES,
  RETRIEVAL_MODES,
  type Citation,
  type HealthResponse,
  type QueryMeta,
  type QueryRequest,
  type QueryResponse,
  type SessionInfo,
  type SessionTurn,
} from "./types";

type Schemas = components["schemas"];

/** POST /query 요청 본문 (서버 형식) */
export type QueryBody = Schemas["QueryRequest"];

/** 두 타입이 서로 대입 가능할 때만 true */
type Mutual<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;

/** 서로 대입 가능하고 키 목록도 같을 때만 true (선택 필드 하나가 빠져도 서로 대입은 되기 때문) */
type IsSame<A, B> = Mutual<A, B> extends true ? Mutual<keyof A, keyof B> : false;

/** snake_case → camelCase (화면 타입의 키를 계약 키와 맞춰 보는 데만 쓴다) */
type CamelCase<S extends string> = S extends `${infer Head}_${infer Tail}`
  ? `${Head}${Capitalize<CamelCase<Tail>>}`
  : S;

/** 화면 타입의 키 목록이 계약 키를 camelCase 로 바꾼 것과 같을 때만 true. 화면 타입이 없으면(undefined) 보지 않는다 */
type ScreenKeysMatch<T, Screen> = [Screen] extends [undefined]
  ? true
  : Mutual<keyof Screen, CamelCase<Extract<keyof T, string>>>;

/** 파싱 결과가 계약 생성 타입(T)과 같고, 화면 타입의 키도 맞을 때만 true */
type Matches<Output, T, Screen> =
  IsSame<Output, T> extends true ? ScreenKeysMatch<T, Screen> : false;

/**
 * 서버 형식 스키마를 계약 생성 타입(T)과 화면 타입(Screen)에 묶는다.
 * 파싱 결과 타입이 T 와 다르거나 Screen 의 키가 T 의 키와 어긋나면 이 자리에서 타입 오류가 난다
 * (계약이 바뀌어 openapi.d.ts 를 다시 만들면 고칠 곳이 드러난다).
 */
function matching<T, Screen = undefined>() {
  return <S extends z.ZodType>(
    schema: S & (Matches<z.output<S>, T, Screen> extends true ? unknown : never),
  ): S => schema;
}

const retrievalModeSchema = z.enum(RETRIEVAL_MODES);
const answerStatusSchema = z.enum(ANSWER_STATUSES);
const errorCodeSchema = z.enum(ERROR_CODES);
// 서버(pydantic)는 UTC 시각을 Z 로, 다른 시간대는 +09:00 처럼 보낸다
const dateTimeSchema = z.iso.datetime({ offset: true });

const citationRaw = matching<Schemas["Citation"], Citation>()(
  z.object({
    source_id: z.string(),
    book_id: z.string(),
    file_name: z.string(),
    page: z.number().int().min(1),
  }),
);

const healthRaw = matching<Schemas["HealthResponse"], HealthResponse>()(
  z.object({
    status: z.literal("ok"),
    index_ready: z.boolean(),
    index_name: z.string().nullish(),
    embedder_id: z.string().nullish(),
    supported_modes: z.array(retrievalModeSchema).optional(),
  }),
);

const queryMetaRaw = matching<Schemas["QueryMeta"], QueryMeta>()(
  z.object({
    retrieval_mode: retrievalModeSchema,
    latency_ms: z.number().nullish(),
    input_tokens: z.number().int().nullish(),
    output_tokens: z.number().int().nullish(),
    cost_usd: z.number().nullish(),
    cache_hit: z.boolean(),
    trace_id: z.string().nullish(),
  }),
);

const queryResponseRaw = matching<Schemas["QueryResponse"], QueryResponse>()(
  z.object({
    request_id: z.string(),
    status: answerStatusSchema,
    answer: z.string(),
    reason: z.string(),
    citations: z.array(citationRaw).optional(),
    error_code: errorCodeSchema.nullish(),
    meta: queryMetaRaw,
  }),
);

const sessionTurnRaw = matching<Schemas["SessionTurn"], SessionTurn>()(
  z.object({
    request_id: z.string(),
    asked_at: dateTimeSchema,
    question: z.string(),
    retrieval_mode: retrievalModeSchema,
    status: answerStatusSchema,
    answer: z.string(),
    citations: z.array(citationRaw).optional(),
  }),
);

const sessionInfoRaw = matching<Schemas["SessionInfo"], SessionInfo>()(
  z.object({
    session_id: z.string(),
    created_at: dateTimeSchema,
    last_active_at: dateTimeSchema,
    expires_at: dateTimeSchema.nullish(),
    turn_count: z.number().int().min(0),
    turns: z.array(sessionTurnRaw).optional(),
  }),
);

function toCitation(raw: Schemas["Citation"]): Citation {
  return { sourceId: raw.source_id, bookId: raw.book_id, fileName: raw.file_name, page: raw.page };
}

function toSessionTurn(raw: Schemas["SessionTurn"]): SessionTurn {
  return {
    requestId: raw.request_id,
    askedAt: Date.parse(raw.asked_at),
    question: raw.question,
    retrievalMode: raw.retrieval_mode,
    status: raw.status,
    answer: raw.answer,
    citations: (raw.citations ?? []).map(toCitation),
  };
}

/** GET /health */
export const healthSchema = healthRaw.transform((raw): HealthResponse => ({
  status: raw.status,
  indexReady: raw.index_ready,
  indexName: raw.index_name ?? null,
  embedderId: raw.embedder_id ?? null,
  supportedModes: raw.supported_modes ?? [],
}));

/** POST /query 응답. 200(answered · needs_clarification · abstained)과 오류 상태 코드(status=error) 모두 이 모양이다 */
export const queryResponseSchema = queryResponseRaw
  // 계약 불변식. 어기면 서버 버그라 bad_response 로 드러낸다
  .superRefine((raw, ctx) => {
    if ((raw.status === "error") !== (raw.error_code != null)) {
      ctx.addIssue({
        code: "custom",
        message: "error_code 는 status=error 일 때만, 그리고 반드시 있어야 한다",
      });
    }
    if (raw.status === "answered" && (raw.citations ?? []).length === 0) {
      ctx.addIssue({ code: "custom", message: "answered 응답은 출처가 1개 이상이어야 한다" });
    }
  })
  .transform((raw): QueryResponse => ({
    requestId: raw.request_id,
    status: raw.status,
    answer: raw.answer,
    reason: raw.reason,
    citations: (raw.citations ?? []).map(toCitation),
    errorCode: raw.error_code ?? null,
    meta: {
      retrievalMode: raw.meta.retrieval_mode,
      latencyMs: raw.meta.latency_ms ?? null,
      inputTokens: raw.meta.input_tokens ?? null,
      outputTokens: raw.meta.output_tokens ?? null,
      costUsd: raw.meta.cost_usd ?? null,
      cacheHit: raw.meta.cache_hit,
      traceId: raw.meta.trace_id ?? null,
    },
  }));

/** GET /session/{session_id} 200 응답 */
export const sessionInfoSchema = sessionInfoRaw
  // 계약 불변식. turns 는 최근 일부라 전체 수(turn_count)를 넘을 수 없다
  .superRefine((raw, ctx) => {
    if ((raw.turns ?? []).length > raw.turn_count) {
      ctx.addIssue({ code: "custom", message: "turns 개수는 turn_count 를 넘을 수 없다" });
    }
  })
  .transform((raw): SessionInfo => ({
    sessionId: raw.session_id,
    createdAt: Date.parse(raw.created_at),
    lastActiveAt: Date.parse(raw.last_active_at),
    expiresAt: raw.expires_at == null ? null : Date.parse(raw.expires_at),
    turnCount: raw.turn_count,
    turns: (raw.turns ?? []).map(toSessionTurn),
  }));

/** QueryResponse 가 아닌 오류 응답 본문 (지금은 GET /session 의 404) */
export const apiErrorSchema = matching<Schemas["ApiError"]>()(
  z.object({ error_code: errorCodeSchema, message: z.string() }),
);

/**
 * 422 응답 본문 (FastAPI 요청 검증 오류). 팀 계약이 아니라 FastAPI 형식이라 생성 타입에 묶지 않고 쓰는 필드만 본다
 */
export const validationErrorSchema = z.object({
  detail: z.array(z.object({ loc: z.array(z.union([z.string(), z.number()])), msg: z.string() })),
});

/** 화면 형식 요청 → 서버 형식 본문 */
export function toQueryBody(request: QueryRequest): QueryBody {
  return {
    question: request.question,
    retrieval_mode: request.retrievalMode,
    session_id: request.sessionId,
  };
}
