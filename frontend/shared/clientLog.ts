// 브라우저가 로그 서버로 보내는 로그 한 건의 형식. 보내는 쪽(src/lib/logger.ts)과 받는 쪽(server/src/app.ts)이 함께 쓴다.

import { z } from "zod";

/** 문구 · 오류 문구 · 계약 위반 내용의 최대 길이 */
export const TEXT_MAX_LENGTH = 1000;
/** 오류 이름 · 코드 · 요청 id 의 최대 길이 */
export const NAME_MAX_LENGTH = 100;
/** 스택의 최대 길이 */
export const STACK_MAX_LENGTH = 4000;

/** 인증 없이 열린 입구로 들어오므로 길이를 제한하고 모르는 키는 받지 않는다 */
export const clientLogSchema = z.strictObject({
  level: z.enum(["warn", "error"]),
  message: z.string().min(1).max(TEXT_MAX_LENGTH),
  requestId: z.string().max(NAME_MAX_LENGTH).optional(),
  error: z
    .strictObject({
      name: z.string().max(NAME_MAX_LENGTH),
      code: z.string().max(NAME_MAX_LENGTH).optional(),
      message: z.string().max(TEXT_MAX_LENGTH).optional(),
      detail: z.string().max(TEXT_MAX_LENGTH).optional(),
      stack: z.string().max(STACK_MAX_LENGTH).optional(),
    })
    .optional(),
});

/** 로그 한 건 */
export type ClientLog = z.infer<typeof clientLogSchema>;
