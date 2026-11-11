import type { ReactNode } from "react";

import type { AnswerStatus } from "../../api/types";
import type { Answer } from "../../lib/chat";
import { Citations } from "../Citations";

/** 답변 카드가 그리는 상태 (error 는 ErrorMessage 가 그린다) */
type CardStatus = Exclude<AnswerStatus, "error">;

/** 상태별 머리말 · 칸 이름 · 상자 색 */
interface CardLook {
  /** 없으면 상자 없이 본문만 (answered) */
  title?: string;
  boxClass?: string;
  answerLabel: string;
  reasonLabel: string;
  citationsLabel: string;
}

const LOOKS: Record<CardStatus, CardLook> = {
  answered: { answerLabel: "결론", reasonLabel: "근거", citationsLabel: "출처" },
  needs_clarification: {
    title: "확인이 필요합니다",
    boxClass:
      "border-sky-200 bg-sky-50 text-sky-950 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-100",
    answerLabel: "확인 질문",
    reasonLabel: "필요한 이유",
    citationsLabel: "판단에 쓴 자료",
  },
  abstained: {
    title: "답변 보류",
    boxClass:
      "border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100",
    answerLabel: "보류 사유",
    reasonLabel: "근거 · 확보할 자료",
    citationsLabel: "판단에 쓴 자료",
  },
};

interface AnswerCardProps {
  answer: Answer;
  /** 되묻기(needs_clarification)에서 "조건 보완해서 묻기"를 눌렀을 때. 없으면 버튼을 숨긴다 */
  onClarify?: () => void;
}

interface SectionProps {
  title: string;
  children: ReactNode;
}

function Section({ title, children }: SectionProps) {
  return (
    <section className="space-y-1 text-sm">
      <h3 className="text-xs font-semibold opacity-70">{title}</h3>
      {children}
    </section>
  );
}

/**
 * 답변 본문: 결론 → 근거 → 출처 순서로 고정.
 * 되묻기는 파란 상자, 보류는 노란 상자로 오류(빨간 상자)와 구분한다. 근거가 없으면(세션 기록) 근거 칸을 뺀다.
 */
export function AnswerCard({ answer, onClarify }: AnswerCardProps) {
  // error 는 쓰는 쪽(AssistantMessage)이 ErrorMessage 로 그려 여기 오지 않는다. 오면 결론 칸 모양으로 둔다
  const look = LOOKS[answer.status === "error" ? "answered" : answer.status];
  const isClarifying = answer.status === "needs_clarification";

  return (
    <div
      className={
        look.boxClass ? `space-y-3 rounded-xl border px-4 py-3 ${look.boxClass}` : "space-y-3"
      }
    >
      {look.title ? <p className="text-sm font-semibold">{look.title}</p> : null}
      <Section title={look.answerLabel}>
        <p className="break-words whitespace-pre-wrap">{answer.answer}</p>
      </Section>
      {answer.reason ? (
        <Section title={look.reasonLabel}>
          <p className="break-words whitespace-pre-wrap">{answer.reason}</p>
        </Section>
      ) : null}
      <Section title={look.citationsLabel}>
        <Citations citations={answer.citations} />
      </Section>
      {isClarifying && onClarify ? (
        <button
          type="button"
          onClick={onClarify}
          className="rounded-lg border border-sky-300 px-3 py-1 text-xs font-medium hover:bg-sky-100 dark:border-sky-800 dark:hover:bg-sky-900/50"
        >
          조건 보완해서 묻기
        </button>
      ) : null}
    </div>
  );
}
