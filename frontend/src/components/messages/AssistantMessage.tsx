import { AnswerCard } from "./AnswerCard";
import { ErrorMessage } from "./ErrorMessage";
import type { AnswerMessage } from "../../lib/chat";
import { REQUEST_ERROR_TEXT } from "../../lib/labels";

interface AssistantMessageProps {
  message: AnswerMessage;
  /** 되묻기에서 "조건 보완해서 묻기"를 눌렀을 때. 원래 질문을 넘긴다 */
  onClarify: (question: string) => void;
}

/**
 * 답변 하나: 기다리는 중 → 상태별 답변 카드 또는 오류 안내.
 * 서버가 status=error 로 답하면 서버의 사용자용 문구를, 응답을 받지 못하면 이유별 안내를 보여 준다.
 */
export function AssistantMessage({ message, onClarify }: AssistantMessageProps) {
  switch (message.state) {
    case "pending":
      return <PendingMessage />;
    case "stopped":
      return <p className="text-xs text-zinc-500">중지됨</p>;
    case "failed":
      return <ErrorMessage text={REQUEST_ERROR_TEXT[message.failure]} />;
    case "done":
      return message.answer.status === "error" ? (
        <ErrorMessage text={message.answer.answer} />
      ) : (
        <AnswerCard answer={message.answer} onClarify={() => onClarify(message.question)} />
      );
  }
}

function PendingMessage() {
  return (
    <div role="status" className="space-y-3">
      <p className="text-sm text-zinc-500 dark:text-zinc-400">자료를 찾아 답변을 만드는 중...</p>
      <div className="space-y-2" aria-hidden="true">
        <div className="h-3 w-11/12 rounded bg-zinc-200 motion-safe:animate-pulse dark:bg-zinc-800" />
        <div className="h-3 w-4/5 rounded bg-zinc-200 motion-safe:animate-pulse dark:bg-zinc-800" />
        <div className="h-3 w-3/5 rounded bg-zinc-200 motion-safe:animate-pulse dark:bg-zinc-800" />
      </div>
    </div>
  );
}
