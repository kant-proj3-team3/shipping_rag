import { MAX_QUESTION_LENGTH } from "../lib/config";

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  /** 빈 입력창 안내. 없으면 기본 문구 */
  placeholder?: string;
}

/** 질문 입력창. 계약 한도(MAX_QUESTION_LENGTH)를 넘는 글자는 입력되지 않는다 */
export function Composer({ value, onChange, placeholder = "질문을 입력하세요" }: ComposerProps) {
  return (
    <div className="mx-auto w-full max-w-3xl px-4">
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        maxLength={MAX_QUESTION_LENGTH}
        placeholder={placeholder}
        aria-label="질문 입력"
        className="block w-full resize-none rounded-2xl border border-zinc-300 bg-white px-4 py-3 text-sm leading-6 shadow-sm outline-none placeholder:text-zinc-400 focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:focus:border-zinc-500"
      />
    </div>
  );
}
