// 대화 화면의 메시지 · 대화 모델과 만들기 · 바꾸기 함수. React 를 쓰지 않는 순수 함수만 둔다.

import type { RequestErrorCode } from "../api/client";
import type { AnswerStatus, Citation, QueryResponse, SessionInfo, SessionTurn } from "../api/types";

/** 사이드바 제목 최대 글자 수 */
const MAX_TITLE_LENGTH = 40;

/** 답변 화면이 그리는 내용. 실시간 응답과 복원한 세션 기록을 모두 이 모양으로 바꾼다 */
export interface Answer {
  status: AnswerStatus;
  /** 결론. needs_clarification 이면 되묻는 문장, abstained 면 보류 이유, error 면 서버의 사용자용 문구 */
  answer: string;
  /** 근거. 세션 기록에는 근거가 없어 null 이다 */
  reason: string | null;
  citations: Citation[];
}

/** 유저 질문 */
export interface QuestionMessage {
  id: string;
  role: "user";
  text: string;
}

/** 답변 진행 상태. done 은 서버가 답한 경우(status=error 포함), failed 는 응답을 받지 못한 경우다 */
export type AnswerState =
  | { state: "pending" }
  | { state: "stopped" }
  | { state: "done"; answer: Answer }
  | { state: "failed"; failure: Exclude<RequestErrorCode, "aborted"> };

/** 답변 하나. question 은 이 답변을 부른 질문이다 (되묻기에서 입력창으로 다시 채울 때 쓴다) */
export type AnswerMessage = { id: string; role: "assistant"; question: string } & AnswerState;

/** 대화 안의 질문 또는 답변 하나 */
export type Message = QuestionMessage | AnswerMessage;

/** 대화 하나 = 서버 세션 하나 */
export interface Conversation {
  /** 대화 id 이자 서버 session_id. 이 대화의 질문은 모두 이 id 로 보낸다 */
  id: string;
  /** 첫 질문 첫 줄 (사이드바 제목) */
  title: string;
  /** 마지막 활동 시각 (ms): 질문을 보낸 때 · 답이 끝난 때. 사이드바 최신순 · 날짜 묶음 기준 */
  updatedAt: number;
  messages: Message[];
}

/** UUID v4 의 i 번째 바이트: 7번째는 버전(4), 9번째는 변형(RFC 4122) 비트를 박는다 */
function uuidV4Byte(byte: number, i: number): number {
  if (i === 6) {
    return (byte & 0x0f) | 0x40;
  }
  if (i === 8) {
    return (byte & 0x3f) | 0x80;
  }
  return byte;
}

// 세션 기록(오래된 것 → 최신 순) → 질문 · 답변 메시지
function messagesFromSession(turns: SessionTurn[]): Message[] {
  return turns.flatMap((turn): Message[] => [
    { id: `${turn.requestId}:q`, role: "user", text: turn.question },
    {
      id: `${turn.requestId}:a`,
      role: "assistant",
      question: turn.question,
      state: "done",
      answer: {
        status: turn.status,
        answer: turn.answer,
        reason: null,
        citations: turn.citations,
      },
    },
  ]);
}

/**
 * 추측할 수 없는 UUID v4. 세션 id 와 메시지 id 에 쓴다.
 * crypto.randomUUID 는 보안 컨텍스트(HTTPS · localhost)에만 있어, HTTP 주소에서도 있는 crypto.getRandomValues 로 만든다
 */
export function newId(): string {
  const hex = Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte, i) =>
    uuidV4Byte(byte, i).toString(16).padStart(2, "0"),
  ).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** /query 응답 → 답변 화면 내용 */
export function answerFromResponse(response: QueryResponse): Answer {
  return {
    status: response.status,
    answer: response.answer,
    reason: response.reason,
    citations: response.citations,
  };
}

/**
 * 세션 기록 → 대화. 브라우저에 남은 내용이 없을 때 서버 기록으로 채운다.
 * 서버는 최근 기록만 주므로, 앞부분이 잘렸으면 제목 앞에 "…" 을 붙여 첫 질문이 아님을 알린다
 */
export function conversationFromSession(info: SessionInfo): Conversation {
  const oldest = titleFrom(info.turns[0]?.question ?? "");
  return {
    id: info.sessionId,
    title: info.turnCount > info.turns.length ? `… ${oldest}` : oldest,
    updatedAt: info.lastActiveAt,
    messages: messagesFromSession(info.turns),
  };
}

/** 사이드바 제목: 첫 줄, 최대 MAX_TITLE_LENGTH 자 */
export function titleFrom(text: string): string {
  const [line = ""] = text.trim().split("\n");
  const chars = Array.from(line);
  return chars.length > MAX_TITLE_LENGTH ? `${chars.slice(0, MAX_TITLE_LENGTH).join("")}…` : line;
}

/** 화면에 보이는 대화 제목. 비었으면 "제목 없음" */
export function titleOf(conversation: Conversation): string {
  return conversation.title || "제목 없음";
}

/** 답변을 기다리는 중인 메시지가 있는지 */
export function hasPendingAnswer(messages: Message[]): boolean {
  return messages.some((m) => m.role === "assistant" && m.state === "pending");
}

/**
 * 서버 세션에 기록이 있어야 하는 대화인지: 서버가 답한 질문이 하나라도 있으면 그렇다.
 * status=error 응답과 응답을 받지 못한 질문은 서버에 기록되지 않는다
 */
export function hasServerTurn(messages: Message[]): boolean {
  return messages.some(
    (m) => m.role === "assistant" && m.state === "done" && m.answer.status !== "error",
  );
}

/** 질문 하나를 보낼 때 쓰는 id 와 시각. 부르는 쪽이 만들어 넘겨 함수는 순수하게 둔다 */
export interface QuestionDraft {
  /** 대화 id (= 세션 id) */
  conversationId: string;
  questionId: string;
  /** 기다리는 답변 메시지 id. 답이 오면 이 메시지를 바꾼다 */
  answerId: string;
  text: string;
  /** 보낸 시각 (ms) */
  now: number;
}

/**
 * 대화에 질문과 기다리는 답변을 붙인 새 대화. 이어서 묻는 대화가 없으면 질문 첫 줄을 제목으로 새로 만든다.
 *
 * @param existing 이어서 묻는 대화. 새 대화면 undefined
 */
export function withQuestion(
  existing: Conversation | undefined,
  draft: QuestionDraft,
): Conversation {
  return {
    id: draft.conversationId,
    title: existing?.title ?? titleFrom(draft.text),
    updatedAt: draft.now,
    messages: [
      ...(existing?.messages ?? []),
      { id: draft.questionId, role: "user", text: draft.text },
      { id: draft.answerId, role: "assistant", question: draft.text, state: "pending" },
    ],
  };
}

/**
 * 한 답변의 진행 상태를 바꾼 새 대화 목록. 그 대화의 updatedAt 도 now 로 바꾼다.
 * 다른 대화 · 메시지 객체는 그대로 둔다 (다시 그리지 않게)
 */
export function withAnswerState(
  conversations: Conversation[],
  conversationId: string,
  answerId: string,
  next: AnswerState,
  now: number,
): Conversation[] {
  return conversations.map((c) =>
    c.id === conversationId
      ? {
          ...c,
          updatedAt: now,
          messages: c.messages.map((m) =>
            m.id === answerId && m.role === "assistant"
              ? { id: m.id, role: "assistant", question: m.question, ...next }
              : m,
          ),
        }
      : c,
  );
}

/** 마지막 답변이 되묻기(needs_clarification)인지. 입력창 안내를 바꾸는 데 쓴다 */
export function isAwaitingClarification(messages: Message[]): boolean {
  const last = messages.at(-1);
  return (
    last?.role === "assistant" &&
    last.state === "done" &&
    last.answer.status === "needs_clarification"
  );
}
