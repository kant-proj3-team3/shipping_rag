import { useEffect, useRef } from "react";

import { AssistantMessage } from "./messages/AssistantMessage";
import { UserMessage } from "./messages/UserMessage";
import type { Message } from "../lib/chat";

// 유즈케이스 문서의 예문: 절차(UC-01) · 보관료 조건(UC-02) · 계산 검증(UC-03) · 되묻기(UC-06)
const EXAMPLES = [
  "예약 접수번호를 받았는데 회신에는 검토 중이라고 적혀 있습니다. 확정으로 보고 준비하면 되나요?",
  "2027년 1월 실제 양하한 S2 일반 건화물 40GP의 기본 무료일수와 일요율을 알려 주세요.",
  "해솔무역 N1 1월 40GP 청구서의 보관료 금액이 맞는지 검증해 주세요.",
  "가온루트 이번 건 마감이 몇 시죠?",
];

interface ChatViewProps {
  messages: Message[];
  /** 되묻기에서 "조건 보완해서 묻기"를 눌렀을 때. 원래 질문을 넘긴다 */
  onClarify: (question: string) => void;
  /** 빈 대화의 예시 질문을 눌렀을 때 */
  onPickExample: (text: string) => void;
}

interface EmptyStateProps {
  onPickExample: (text: string) => void;
}

/** 질문 · 답변 목록. 새 메시지가 붙으면 맨 아래로 내린다 */
export function ChatView({ messages, onClarify, onPickExample }: ChatViewProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

  if (messages.length === 0) {
    return <EmptyState onPickExample={onPickExample} />;
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto" role="region" aria-label="대화">
      <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">
        {messages.map((m) =>
          m.role === "user" ? (
            <UserMessage key={m.id} message={m} />
          ) : (
            <AssistantMessage key={m.id} message={m} onClarify={onClarify} />
          ),
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}

function EmptyState({ onPickExample }: EmptyStateProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 overflow-y-auto p-6 text-center">
      <div>
        <h2 className="text-xl font-semibold">무엇이 궁금하신가요?</h2>
        <p className="mt-2 text-sm text-zinc-500">
          부산–LA 일반 건화물의 예약 · 서류 절차와 보관료를 물으면 자료집을 근거로 결론 · 근거 ·
          출처를 답합니다.
        </p>
      </div>
      <ul className="flex w-full max-w-md flex-col gap-2">
        {EXAMPLES.map((text) => (
          <li key={text}>
            <button
              type="button"
              onClick={() => onPickExample(text)}
              className="w-full rounded-xl border border-zinc-200 px-4 py-2.5 text-left text-sm text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
            >
              {text}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
