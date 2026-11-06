// 대화 화면의 메시지 모델과 만들기 · 바꾸기 함수. React 를 쓰지 않는 순수 함수만 둔다.

import type { RequestErrorCode } from "../api/client";
import type { AnswerStatus, Citation, QueryResponse } from "../api/types";

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

/** 메시지 id */
export function newId(): string {
  return crypto.randomUUID();
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

/** 답변을 기다리는 중인 메시지가 있는지 */
export function isWaiting(messages: Message[]): boolean {
  return messages.some((m) => m.role === "assistant" && m.state === "pending");
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
