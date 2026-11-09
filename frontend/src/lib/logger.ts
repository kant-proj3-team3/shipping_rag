// 로그는 이 파일 한 곳을 거친다. 환경 분기도 여기서만 본다.

import { z } from "zod";

import { NAME_MAX_LENGTH, TEXT_MAX_LENGTH, type ClientLog } from "../../shared/clientLog";
import { RequestError } from "../api/client";

const CLIENT_LOG_PATH = "/client-logs"; // nginx 가 로그 서버로 넘긴다
// 같은 오류가 되풀이되면 요청 수 제한(nginx.conf)을 다 써서 다른 로그까지 버려진다. 이 시간 안의 반복은 한 번만 보낸다
const REPEAT_WINDOW_MS = 5000;
const MAX_TRACKED_LOGS = 100;

type ClientLogError = NonNullable<ClientLog["error"]>;

interface LogContext {
  /** 서버 응답의 request_id. 백엔드 기록과 맞춰 볼 때 쓴다 */
  requestId?: string;
}

// history · storage 처럼 React 밖에서도 부르는 로거라 Provider 로 주입하지 않고 모듈에 둔다
const lastSentAt = new Map<string, number>();

function isRepeat(key: string): boolean {
  const now = Date.now();
  const last = lastSentAt.get(key);
  if (last !== undefined && now - last < REPEAT_WINDOW_MS) {
    return true;
  }
  if (lastSentAt.size >= MAX_TRACKED_LOGS) {
    lastSentAt.clear();
  }
  lastSentAt.set(key, now);
  return false;
}

/** zod 문구는 기대한 형식만 말하고 받은 값을 담지 않아 서버로 보내도 된다 */
function issuesText(error: z.ZodError): string {
  return error.issues
    .map((issue) => `${issue.path.map(String).join(".") || "(root)"}: ${issue.message}`)
    .join("; ")
    .slice(0, TEXT_MAX_LENGTH);
}

function summarizeRequestError(error: RequestError): ClientLogError {
  return {
    name: error.name,
    code: error.code,
    message: error.message.slice(0, TEXT_MAX_LENGTH),
    detail: error.cause instanceof z.ZodError ? issuesText(error.cause) : undefined,
  };
}

function nameOnly(error: Error): ClientLogError {
  return { name: error.name.slice(0, NAME_MAX_LENGTH) };
}

/** 경고로 다루는 오류. 저장소 오류의 문구에는 저장본 조각이 섞일 수 있어(JSON.parse 등) 이름만 보낸다 */
function summarizeExpected(cause: unknown): ClientLogError | undefined {
  if (cause instanceof RequestError) {
    return summarizeRequestError(cause);
  }
  return cause instanceof Error ? nameOnly(cause) : undefined;
}

function sendToLogServer(log: ClientLog): void {
  const { level, error } = log;
  const message = log.message.slice(0, TEXT_MAX_LENGTH);
  if (isRepeat(JSON.stringify([level, message, error?.name, error?.code, error?.message]))) {
    return;
  }
  // 로그를 못 보내도 화면은 그대로 동작해야 하고, 이 실패를 다시 로그로 남기면 같은 실패가 되풀이된다
  void fetch(CLIENT_LOG_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...log, message }),
    keepalive: true, // 페이지를 닫는 중에 남긴 로그도 보낸다
  }).catch(() => undefined);
}

/**
 * 화면에 알릴 필요는 없지만 원인을 추적할 때 볼 내용(error_code · 요청 실패 원인)을 남긴다.
 * 콘솔에 나오고, 배포 빌드에서는 로그 서버에도 남는다. 테스트 출력에는 나오지 않는다.
 *
 * @param message 서버 로그에 그대로 남고 같은 오류를 묶는 기준이 된다. 질문 · 답변 · 세션 id 나 요청마다 달라지는 값을 넣지 않는다
 * @param cause 원본 예외처럼 함께 볼 값. 콘솔에는 그대로 나오고, 서버에는 오류 요약만 간다 (오류가 아닌 값은 보내지 않는다)
 */
export function logWarning(message: string, cause?: unknown, context?: LogContext): void {
  if (import.meta.env.MODE === "test") {
    return;
  }
  console.warn(message, cause);
  if (import.meta.env.PROD) {
    sendToLogServer({
      level: "warn",
      message,
      requestId: context?.requestId?.slice(0, NAME_MAX_LENGTH),
      error: summarizeExpected(cause),
    });
  }
}
