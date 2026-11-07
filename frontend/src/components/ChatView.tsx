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
  /** 대화의 서버 세션을 확인하는 중. 보여 줄 메시지가 없으면 불러오는 중으로 그린다 */
  isChecking: boolean;
  /** 서버에서 만료된 대화. 메시지 아래에 안내를 붙인다 */
  isExpired: boolean;
  /** 되묻기에서 "조건 보완해서 묻기"를 눌렀을 때. 원래 질문을 넘긴다 */
  onClarify: (question: string) => void;
  /** 빈 대화의 예시 질문을 눌렀을 때 */
  onPickExample: (text: string) => void;
}

interface EmptyStateProps {
  onPickExample: (text: string) => void;
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

/** 질문 · 답변 목록. 질문을 보내면 맨 아래로, 답이 오면 그 답의 처음(결론)이 보이게 내린다 */
export function ChatView({
  messages,
  isChecking,
  isExpired,
  onClarify,
  onPickExample,
}: ChatViewProps) {
  const endRef = useRef<HTMLDivElement>(null);
  const lastRef = useRef<HTMLDivElement>(null);
  const last = messages.at(-1);
  const isAnswerDone = last?.role === "assistant" && last.state !== "pending";

  // 답이 오면 메시지 수는 그대로라(기다리는 중 → 답) 마지막 답의 상태도 본다.
  // 긴 답은 맨 아래로 내리면 결론이 위로 밀려나므로 답의 처음에 맞춘다 (짧으면 결국 맨 아래까지 내려간다)
  useEffect(() => {
    if (isAnswerDone) {
      lastRef.current?.scrollIntoView({ block: "start" });
    } else {
      endRef.current?.scrollIntoView({ block: "end" });
    }
  }, [messages.length, isAnswerDone]);

  if (messages.length === 0 && isChecking) {
    return (
      <p role="status" className="flex flex-1 items-center justify-center text-sm text-zinc-500">
        이전 대화를 불러오는 중...
      </p>
    );
  }
  if (messages.length === 0) {
    return <EmptyState onPickExample={onPickExample} />;
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto" role="region" aria-label="대화">
      <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">
        {messages.map((m) => (
          <div key={m.id} ref={m === last ? lastRef : undefined} className="scroll-mt-6">
            {m.role === "user" ? (
              <UserMessage message={m} />
            ) : (
              <AssistantMessage message={m} onClarify={onClarify} />
            )}
          </div>
        ))}
        {isExpired ? (
          <p
            role="status"
            className="rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-3 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400"
          >
            서버에서 만료된 대화입니다. 내용은 그대로 볼 수 있고, 다음 질문은 새 대화로 시작합니다.
          </p>
        ) : null}
        <div ref={endRef} />
      </div>
    </div>
  );
}
