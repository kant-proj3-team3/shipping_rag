// 서버 응답 검증 · 변환. 계약 모양 검증과 camelCase 변환은 생성 코드(generated/schemas.generated.ts)가 한다.
// 여기서는 openapi.json 에 나오지 않는 계약 불변식(packages/common 의 validator)만 덧붙인다.

import {
  apiErrorRaw,
  healthResponseRaw,
  httpValidationErrorRaw,
  queryResponseRaw,
  sessionInfoRaw,
  toHTTPValidationError,
  toHealthResponse,
  toQueryResponse,
  toSessionInfo,
} from "./generated/schemas.generated";

/** 화면 형식 요청 → 서버 형식 본문 (POST /query) */
export { toQueryRequestBody as toQueryBody } from "./generated/schemas.generated";

/** GET /health */
export const healthSchema = healthResponseRaw.transform(toHealthResponse);

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
  .transform(toQueryResponse);

/** GET /session/{session_id} 200 응답 */
export const sessionInfoSchema = sessionInfoRaw
  // 계약 불변식. turns 는 최근 일부라 전체 수(turn_count)를 넘을 수 없다
  .superRefine((raw, ctx) => {
    if ((raw.turns ?? []).length > raw.turn_count) {
      ctx.addIssue({ code: "custom", message: "turns 개수는 turn_count 를 넘을 수 없다" });
    }
  })
  .transform(toSessionInfo);

/** QueryResponse 가 아닌 오류 응답 본문 (지금은 GET /session 의 404). 서버 형식 그대로 읽는다 */
export const apiErrorSchema = apiErrorRaw;

/** 422 응답 본문 (FastAPI 요청 검증 오류) */
export const validationErrorSchema = httpValidationErrorRaw.transform(toHTTPValidationError);
