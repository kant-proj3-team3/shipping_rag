// 서버 세션 확인 결과를 대화 화면 상태로 바꾸는 순수 함수. React 를 쓰지 않는다.

import { conversationFromSession, hasServerTurn, type Conversation } from "./chat";
import type { SessionInfo } from "../api/types";

/**
 * 보고 있는 대화의 세션 상태.
 * - checking: GET /session 으로 확인하는 중 (보내지 않는다)
 * - live: 같은 세션으로 이어서 묻는다 (확인하지 못했어도 브라우저에 내용이 있으면)
 * - expired: 서버에서 만료됐다. 다음 질문은 새 대화로 시작한다
 * - missing: 브라우저에도 없고 서버 기록으로도 채울 수 없다. 새 대화 화면으로 연다
 */
export type SessionStatus = "checking" | "live" | "expired" | "missing";

/** 세션 확인 요청의 진행 상태 */
export type SessionLookup =
  /** 확인하지 않는 대화 (새 대화 화면 · 방금 보낸 대화 · 답을 받는 중인 대화) */
  | { state: "skipped" }
  | { state: "pending" }
  /** 응답을 받지 못했다 */
  | { state: "failed" }
  /** 응답을 받았다. 없거나 만료된 세션이면 null */
  | { state: "done"; info: SessionInfo | null };

/** 보고 있는 대화의 화면 상태 */
export interface SessionView {
  status: SessionStatus;
  /** 브라우저에 없어 서버 기록으로 채운 대화. 다음 질문을 보낼 때 브라우저에 저장한다 */
  restored: Conversation | undefined;
}

// 브라우저에 내용이 있는 대화. 서버가 답한 적 없는 대화는 404 여도 세션이 아직 없을 뿐이고,
// 확인하지 못했으면 같은 세션으로 이어서 묻는다
function localStatusOf(lookup: SessionLookup, local: Conversation): SessionStatus {
  if (lookup.state === "pending") {
    return "checking";
  }
  const isGone = lookup.state === "done" && lookup.info === null;
  return isGone && hasServerTurn(local.messages) ? "expired" : "live";
}

/**
 * 세션 확인 결과와 브라우저에 남은 대화로 화면 상태를 정한다.
 *
 * @param local 브라우저에 저장된, 보고 있는 대화. 없으면 undefined
 */
export function sessionViewOf(lookup: SessionLookup, local: Conversation | undefined): SessionView {
  if (local !== undefined) {
    return { status: localStatusOf(lookup, local), restored: undefined };
  }
  if (lookup.state === "pending") {
    return { status: "checking", restored: undefined };
  }
  if (lookup.state === "done" && lookup.info !== null && lookup.info.turns.length > 0) {
    return { status: "live", restored: conversationFromSession(lookup.info) };
  }
  return { status: "missing", restored: undefined };
}
