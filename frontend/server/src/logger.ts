// 로그를 남기는 곳: 콘솔(docker logs)과 날짜별 텍스트 파일에 같은 줄을 남기고, 하루 한도를 넘으면 넘침 파일로 이어 쓴다.

import path from "node:path";

import winston from "winston";
import DailyRotateFile from "winston-daily-rotate-file";

import { createDailyQuota } from "./quota.ts";

const MAX_FILE_SIZE = "10m";
// 날짜별 로그. 하루 양은 createLogSink 의 dailyLimitBytes 로 묶고 14일 보관한다
const DAILY_FILES: LogFiles = {
  filename: "client-%DATE%.log",
  maxFiles: "14d",
  auditFile: ".client-audit.json",
};
// 하루 한도를 넘은 로그. 인증 없는 입구라 디스크가 차지 않도록 개수로 묶어(100MB) 오래된 넘침 파일부터 지운다
const OVERFLOW_FILES: LogFiles = {
  filename: "client-%DATE%-overflow.log",
  maxFiles: 10,
  auditFile: ".client-overflow-audit.json",
};
const LEVEL_WIDTH = 5;
const STACK_INDENT = "    ";
const DEFAULT_SOURCE = "server";

interface LogFiles {
  filename: string;
  /** 숫자면 파일 개수, "14d" 꼴이면 보관 일수 */
  maxFiles: number | string;
  auditFile: string;
}

interface LogEntry {
  level: "info" | "warn" | "error";
  message: string;
  /** 어디서 온 로그인가. 없으면 이 서버 */
  source?: string;
  /** 줄 끝에 key=value 로 붙이는 값. 값이 undefined 면 붙이지 않는다 */
  fields?: Record<string, string | undefined>;
  /** 다음 줄부터 들여써서 남기는 스택 */
  stack?: string;
}

/** 로그를 남기는 곳 */
export interface LogSink {
  /** 로그 한 줄을 남긴다 */
  write: (entry: LogEntry) => void;
}

function pad(value: number, width = 2): string {
  return String(value).padStart(width, "0");
}

/** 컨테이너의 TZ 기준 현지 시각 (log4net 기본 형식: 2026-11-09 14:30:28,469) */
function localTimestamp(): string {
  const now = new Date();
  const date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  return `${date} ${time},${pad(now.getMilliseconds(), 3)}`;
}

// 브라우저가 보낸 문구는 믿을 수 없다. 줄바꿈 · 제어 · 서식 문자는 가짜 줄을 만들거나 보이는 내용을 바꿀 수 있어 공백으로 바꾸고,
// key=value 꼴은 띄어 써서 줄 끝의 실제 값(issue= 등)으로 검색되지 않게 한다
function safeText(text: string): string {
  return text.replace(/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]+/gu, " ").replace(/([\p{L}\p{N}_]+)=/gu, "$1 =");
}

function fieldValue(value: string): string {
  return /^[\w.:/-]+$/.test(value) ? value : JSON.stringify(safeText(value));
}

/** 2026-11-09 14:30:28,469 WARN  [browser] 문구 issue=a1f3c9 code=network */
function formatLine(entry: LogEntry, timestamp: string): string {
  const level = entry.level.toUpperCase().padEnd(LEVEL_WIDTH);
  const source = entry.source ?? DEFAULT_SOURCE;
  const fields = Object.entries(entry.fields ?? {}).flatMap(([name, value]) =>
    value === undefined ? [] : [`${name}=${fieldValue(value)}`],
  );
  const head = `${timestamp} ${level} [${source}] ${safeText(entry.message)}`;
  const line = [head, ...fields].join(" ");
  if (entry.stack === undefined) {
    return line;
  }
  // 들여쓴 줄은 앞 줄에 딸린 스택이다. 맨 앞에서 시작하는 줄은 항상 로거가 쓴 줄이다
  const stack = entry.stack.split(/\r?\n/).map((part) => `${STACK_INDENT}${safeText(part)}`);
  return [line, ...stack].join("\n");
}

// 파일이 MAX_FILE_SIZE 를 넘으면 번호를 붙여 이어 쓴다. 파일을 쓰지 못해도 멈추지 않고 콘솔에는 계속 남긴다
function createFileLogger(dir: string, files: LogFiles): winston.Logger {
  const logger = winston.createLogger({
    level: "info",
    format: winston.format.combine(
      winston.format.timestamp({ format: localTimestamp }),
      // write 가 넘긴 LogEntry 에 바로 앞 포맷이 timestamp 를 더해 돌아온다
      winston.format.printf((info) => formatLine(info as LogEntry, String(info.timestamp))),
    ),
    transports: [new winston.transports.Console()],
  });
  // 쓸 때마다 같은 오류가 나도 콘솔이 오류로 채워지지 않게 같은 원인은 한 번만 알린다
  let lastError = "";
  const reportFileError = (error: unknown): void => {
    const text = String(error);
    if (text !== lastError) {
      lastError = text;
      console.error(`로그 파일에 쓰지 못해 콘솔에만 남긴다: ${text}`);
    }
  };
  logger.on("error", reportFileError);
  try {
    const file = new DailyRotateFile({
      dirname: dir,
      filename: files.filename,
      datePattern: "YYYY-MM-DD",
      maxSize: MAX_FILE_SIZE,
      maxFiles: files.maxFiles,
      auditFile: path.join(dir, files.auditFile),
    });
    // 파일 스트림 오류는 winston 을 거치지 않아 여기서 듣지 않으면 프로세스가 죽는다
    file.logStream.on("error", reportFileError);
    logger.add(file);
  } catch (e) {
    reportFileError(e);
  }
  return logger;
}

/**
 * 로그를 남길 곳을 만든다. 날짜별 파일(client-2026-11-09.log)에 남기고, 하루 한도를 넘으면 넘침 파일(client-2026-11-09-overflow.log)에 이어 쓴다.
 *
 * @param dir 로그 파일을 둘 폴더. 없으면 만든다
 * @param dailyLimitBytes 날짜별 파일에 남길 하루 양
 */
export function createLogSink(dir: string, dailyLimitBytes: number): LogSink {
  const daily = createFileLogger(dir, DAILY_FILES);
  const quota = createDailyQuota(dailyLimitBytes);
  // 한도를 넘기 전에는 빈 넘침 파일이 생기지 않도록 처음 쓸 때 만든다
  let overflow: winston.Logger | undefined;

  // winston 에 문구를 인자로 따로 넘기면 %s 같은 토큰을 보고 나머지 값을 버린다. 브라우저가 보낸 문구가 오므로 항상 객체 하나로 넘긴다.
  // winston 이 받은 객체를 고치므로 복사해서 넘긴다
  function write(entry: LogEntry): void {
    const usage = quota.take(Buffer.byteLength(JSON.stringify(entry)));
    if (usage === "allowed") {
      daily.log({ ...entry });
      return;
    }
    if (usage === "just_exhausted") {
      daily.log({ level: "warn", message: "오늘 로그 한도를 넘어 넘침 파일에 이어 남긴다" });
    }
    overflow ??= createFileLogger(dir, OVERFLOW_FILES);
    overflow.log({ ...entry });
  }

  return { write };
}
