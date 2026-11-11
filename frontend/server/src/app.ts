// 화면 로그를 받는 HTTP 앱. 인증 없이 열린 입구라 본문을 좁게 검증하고, 통과한 내용만 남긴다.

import { createHash } from "node:crypto";

import express, { type ErrorRequestHandler, type Express } from "express";

import type { LogSink } from "./logger.ts";
import type { StackMapper } from "./sourceMaps.ts";
import { clientLogSchema, type ClientLog } from "../../shared/clientLog.ts";

const BODY_LIMIT = "16kb"; // nginx.conf 의 client_max_body_size 와 같다
const USER_AGENT_MAX_LENGTH = 300;
const ISSUE_KEY_LENGTH = 6;

/**
 * 같은 오류에 같은 값을 준다. 숫자는 매번 달라질 수 있어(HTTP 상태 · 개수) 빼고 계산한다.
 * 스택 위치를 알면 오류 문구 대신 위치로 묶는다. 축약된 빌드의 문구(e is not a function)는 서로 다른 버그에 같고 빌드마다 바뀐다
 */
function issueKey({ message, error }: ClientLog, location: string | undefined): string {
  const text = [message, error?.name, error?.code, location === undefined ? error?.message : ""]
    .map((part) => part ?? "")
    .join("|")
    .replace(/\d+/g, "#");
  return createHash("sha256")
    .update(`${text}|${location ?? ""}`)
    .digest("hex")
    .slice(0, ISSUE_KEY_LENGTH);
}

// 깨진 JSON · 너무 큰 본문은 상태 코드만 돌려준다. express 기본 처리기는 이런 요청마다 스택을 콘솔에 찍는다.
// 상태 코드가 없는 오류는 이 서버의 문제라 원인을 남긴다
function createErrorHandler(sink: LogSink): ErrorRequestHandler {
  return (error: Error & { status?: number }, _req, res, next) => {
    if (res.headersSent) {
      next(error);
      return;
    }
    if (error.status === undefined) {
      sink.write({ level: "error", message: "요청을 처리하지 못했다", stack: error.stack });
      res.sendStatus(500);
      return;
    }
    res.sendStatus(error.status);
  };
}

/**
 * 로그 입구(POST /client-logs)와 상태 확인(GET /healthz)을 가진 앱을 만든다.
 *
 * @param sink 받은 로그를 남길 곳
 * @param mapStack 스택을 원본 소스 위치로 바꾸는 함수
 */
export function createApp(sink: LogSink, mapStack: StackMapper): Express {
  const app = express();
  app.disable("x-powered-by");

  app.get("/healthz", (_req, res) => {
    res.json({ status: "ok" });
  });

  app.post("/client-logs", express.json({ limit: BODY_LIMIT }), (req, res) => {
    const parsed = clientLogSchema.safeParse(req.body);
    if (!parsed.success) {
      res.sendStatus(400);
      return;
    }
    const { level, message, requestId, error } = parsed.data;
    const mapped = error?.stack === undefined ? undefined : mapStack(error.stack);
    sink.write({
      level,
      message,
      source: "browser",
      stack: mapped?.stack,
      fields: {
        issue: issueKey(parsed.data, mapped?.location),
        error: error?.name,
        code: error?.code,
        cause: error?.message,
        detail: error?.detail,
        request: requestId,
        ua: req.get("user-agent")?.slice(0, USER_AGENT_MAX_LENGTH),
      },
    });
    res.sendStatus(204);
  });

  app.use(createErrorHandler(sink));
  return app;
}
