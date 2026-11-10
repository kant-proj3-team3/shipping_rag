import { AnswerCard } from "./AnswerCard";
import { ErrorMessage } from "./ErrorMessage";
import { SealLoader } from "./SealLoader";
import type { AnswerMessage } from "../../lib/chat";
import { REQUEST_ERROR_TEXT, UNKNOWN_ERROR_TEXT } from "../../lib/labels";

interface AssistantMessageProps {
  message: AnswerMessage;
  /** 되묻기에서 "조건 보완해서 묻기"를 눌렀을 때. 원래 질문을 넘긴다 */
  onClarify: (question: string) => void;
}

function PendingMessage() {
  return (
    <div className="flex items-center gap-3">
      <SealLoader />
      <p className="text-sm text-zinc-500 dark:text-zinc-400">오늘도 해내는 중...</p>
    </div>
  );
}

// 서버의 사용자용 오류 문구. 계약은 빈 문구도 허용해, 비어 있으면 알 수 없는 오류로 안내한다
function serverErrorText(text: string): string {
  return text.trim() === "" ? UNKNOWN_ERROR_TEXT : text;
}

/**
 * 답변 하나: 기다리는 중 → 상태별 답변 카드 또는 오류 안내.
 * 서버가 status=error 로 답하면 서버의 사용자용 문구를(비어 있으면 알 수 없는 오류 안내를),
 * 응답을 받지 못하면 이유별 안내를 보여 준다.
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
        <ErrorMessage text={serverErrorText(message.answer.answer)} />
      ) : (
        <AnswerCard answer={message.answer} onClarify={() => onClarify(message.question)} />
      );
  }
}
