// 대화 목록 저장 (브라우저 저장소). 서버 세션 기록에는 근거 · 오류 안내가 없어, 화면이 보던 내용을 브라우저에 따로 남긴다.
// 읽기 · 쓰기는 storage.ts 의 readItem · writeItem 으로 감싸 저장할 수 없는 환경(시크릿 창 · 차단)에서도 화면이 동작한다.
// 목록 저장만 용량 초과 때 줄여서 다시 쓰려고 예외를 직접 잡는다.
// 저장 형식은 화면 형식(lib/chat.ts) 그대로다.

import { z } from "zod";

import { hasPendingAnswer, type Conversation, type Message } from "./chat";
import { CURRENT_STORAGE_KEY, HISTORY_STORAGE_KEY, MAX_CONVERSATIONS } from "./config";
import { logWarning } from "./logger";
import { readItem, writeItem, type KeyValueStorage } from "./storage";
import { REQUEST_ERROR_CODES } from "../api/client";
import { ANSWER_STATUSES, SESSION_ID_PATTERN } from "../api/types";

/** 저장본 형식 버전. 저장 모양이 바뀌면 올린다 (다른 버전 저장본은 빈 목록으로 본다) */
const HISTORY_VERSION = 1;

/** 용량이 넘칠 때 남기는 비율 (오래된 20% 를 버리고 다시 쓴다) */
const SHRINK_RATIO = 0.8;

/** 저장소 용량 초과 예외 이름. NS_ERROR_DOM_QUOTA_REACHED 는 구버전 Firefox 가 쓴다 */
const QUOTA_ERROR_NAMES: readonly string[] = ["QuotaExceededError", "NS_ERROR_DOM_QUOTA_REACHED"];

/** 저장 결과. trimmed 는 용량이 모자라 오래된 대화 일부를 저장본에서 뺀 경우다 */
export type SaveResult = "saved" | "trimmed" | "failed";

/** 불러온 대화 목록 */
export interface LoadedHistory {
  /** 최신 활동순 */
  conversations: Conversation[];
  /**
   * 보고 있던 대화. 없으면 새 대화 화면.
   * 목록에 없는 id 일 수 있다 (목록 저장에 실패한 경우) — 서버 기록으로 채운다
   */
  currentId: string | undefined;
}

const answerSchema = z.object({
  status: z.enum(ANSWER_STATUSES),
  answer: z.string(),
  reason: z.string().nullable(),
  citations: z.array(
    z.object({ sourceId: z.string(), bookId: z.string(), fileName: z.string(), page: z.number() }),
  ),
});

const answerBase = { id: z.string(), role: z.literal("assistant"), question: z.string() };

const messageSchema: z.ZodType<Message> = z
  .union([
    z.object({ id: z.string(), role: z.literal("user"), text: z.string() }),
    z.object({ ...answerBase, state: z.literal("pending") }),
    z.object({ ...answerBase, state: z.literal("stopped") }),
    z.object({ ...answerBase, state: z.literal("done"), answer: answerSchema }),
    z.object({
      ...answerBase,
      state: z.literal("failed"),
      failure: z.enum(REQUEST_ERROR_CODES).exclude(["aborted"]),
    }),
  ])
  // 받는 도중 탭이 닫혀 pending 으로 남은 답변은 중지된 것으로 본다
  .transform((m): Message =>
    m.role === "assistant" && m.state === "pending" ? { ...m, state: "stopped" } : m,
  );

// 메시지는 하나씩 검증한다 (readConversation). 하나가 깨졌다고 대화 전체를 버리지 않는다
const conversationSchema = z.object({
  id: z.string().regex(SESSION_ID_PATTERN),
  title: z.string(),
  updatedAt: z.number(),
  messages: z.array(z.unknown()),
});

/** 저장본의 대화 하나. 깨진 메시지는 빼고, 남은 메시지가 없으면 대화를 버린다 */
function readConversation(value: unknown): Conversation[] {
  const parsed = conversationSchema.safeParse(value);
  if (!parsed.success) {
    return [];
  }
  const messages = parsed.data.messages.flatMap((item) => {
    const message = messageSchema.safeParse(item);
    return message.success ? [message.data] : [];
  });
  if (messages.length < parsed.data.messages.length) {
    logWarning(`깨진 메시지 ${parsed.data.messages.length - messages.length}개를 버렸다`);
  }
  return messages.length > 0 ? [{ ...parsed.data, messages }] : [];
}

/** 저장본의 대화 목록. 저장본이 없거나 깨졌거나 다른 버전이면 undefined */
function readList(raw: string | null): unknown[] | undefined {
  if (raw === null) {
    return undefined;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    logWarning("대화 목록 저장본이 깨져 있어 버린다", e);
    return undefined;
  }
  return isObject(parsed) &&
    parsed.version === HISTORY_VERSION &&
    Array.isArray(parsed.conversations)
    ? parsed.conversations
    : undefined;
}

function readConversations(list: unknown[]): Conversation[] {
  const conversations = sortByRecent(list.flatMap(readConversation));
  if (conversations.length < list.length) {
    logWarning(`깨진 대화 ${list.length - conversations.length}개를 버렸다`);
  }
  return conversations;
}

function isQuotaError(e: unknown): boolean {
  return e instanceof DOMException && QUOTA_ERROR_NAMES.includes(e.name);
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** 저장된 대화 목록을 불러온다. 깨진 대화 · 메시지는 버리고 나머지는 살린다 */
export function loadHistory(storage: KeyValueStorage): LoadedHistory {
  const raw = readItem(storage, HISTORY_STORAGE_KEY, "대화 목록");
  const current = readItem(storage, CURRENT_STORAGE_KEY, "보고 있던 대화");
  const conversations = readConversations(readList(raw) ?? []);
  const currentId = current !== null && SESSION_ID_PATTERN.test(current) ? current : undefined;
  return { conversations, currentId };
}

/**
 * 대화 목록을 저장한다 (최신순 최대 MAX_CONVERSATIONS 개). 용량이 넘치면 오래된 대화부터 줄여 다시 쓴다.
 *
 * @returns 그대로 저장했으면 saved, 일부를 줄였으면 trimmed, 저장할 수 없으면 failed
 */
export function saveHistory(storage: KeyValueStorage, conversations: Conversation[]): SaveResult {
  let keep = sortByRecent(conversations).slice(0, MAX_CONVERSATIONS);
  let result: SaveResult = "saved";
  for (;;) {
    try {
      storage.setItem(
        HISTORY_STORAGE_KEY,
        JSON.stringify({ version: HISTORY_VERSION, conversations: keep }),
      );
      return result;
    } catch (e) {
      if (!isQuotaError(e) || keep.length <= 1) {
        logWarning("대화 목록을 저장하지 못했다", e);
        return "failed";
      }
      keep = keep.slice(0, Math.floor(keep.length * SHRINK_RATIO));
      result = "trimmed";
    }
  }
}

/** 보고 있는 대화를 남긴다 (새로고침하면 다시 연다). 없으면 새 대화 화면 */
export function saveCurrentId(storage: KeyValueStorage, id: string | undefined): void {
  // 못 남겨도 새로고침하면 새 대화 화면으로 열릴 뿐이다
  writeItem(storage, CURRENT_STORAGE_KEY, id, "보고 있는 대화");
}

/** 최신 활동순으로 정렬한 새 배열 */
export function sortByRecent(conversations: Conversation[]): Conversation[] {
  return [...conversations].sort((a, b) => b.updatedAt - a.updatedAt);
}

/**
 * 다른 탭이 저장한 목록을 이 탭의 목록에 합친다 (저장할 때 서로의 대화를 덮어쓰지 않게).
 * - 양쪽에 다 있는 대화는 더 최근에 바뀐 쪽을 쓴다. 같으면 이 탭 것을 쓴다 (받는 중인 답변이 저장본에는 중지로 읽힌다)
 * - 저장본에 없는 대화는 다른 탭이 지운 것으로 보고 뺀다. 이 탭에서 답변을 받는 중인 대화는 남긴다
 * - 보고 있던 대화가 빠지면 새 대화 화면으로 돌린다
 *
 * @param isUnsaved 이 탭이 마지막 저장에 실패했다. 저장본에 없는 대화가 이 탭에서만 있는(저장하지 못한) 대화일 수 있어 빼지 않는다
 */
export function mergeFromOtherTab(
  local: LoadedHistory,
  stored: Conversation[],
  isUnsaved = false,
): LoadedHistory {
  const localById = new Map(local.conversations.map((c) => [c.id, c]));
  const storedIds = new Set(stored.map((c) => c.id));
  const merged = stored.map((theirs) => {
    const mine = localById.get(theirs.id);
    return mine !== undefined && mine.updatedAt >= theirs.updatedAt ? mine : theirs;
  });
  const kept = local.conversations.filter(
    (c) => !storedIds.has(c.id) && (isUnsaved || hasPendingAnswer(c.messages)),
  );
  const conversations = sortByRecent([...kept, ...merged]);
  // 목록에 없던 보고 있던 대화(서버 기록으로 채우는 중)는 건드리지 않는다
  const isCurrentListed = localById.has(local.currentId ?? "");
  const isGone = isCurrentListed && !conversations.some((c) => c.id === local.currentId);
  return { conversations, currentId: isGone ? undefined : local.currentId };
}

/**
 * 저장 직전에 저장본을 다시 읽어 합친다. 저장은 목록 전체를 덮어쓰므로, 다른 탭의 변경을 받기 전에 저장해도 그 변경을 지우지 않게 한다.
 * 저장본이 없거나 읽을 수 없으면 그대로 돌려준다 (빈 목록과 합치면 이 탭의 대화를 지운 것으로 보게 된다)
 */
export function mergeStoredHistory(storage: KeyValueStorage, local: LoadedHistory): LoadedHistory {
  const list = readList(readItem(storage, HISTORY_STORAGE_KEY, "대화 목록"));
  return list === undefined ? local : mergeFromOtherTab(local, readConversations(list));
}
