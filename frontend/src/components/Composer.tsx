import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  type KeyboardEvent,
  type RefObject,
} from "react";

import { useMediaQuery } from "../hooks/useMediaQuery";
import { MAX_QUESTION_LENGTH } from "../lib/config";

/** IME 합성 중 keydown 의 keyCode (일부 브라우저는 isComposing 대신 이것만 준다) */
const IME_KEY_CODE = 229;

/** 터치가 주 입력인 기기. 화면 키보드에는 Shift+Enter 가 없어 Enter 를 줄바꿈으로 둔다 */
const TOUCH_QUERY = "(pointer: coarse)";

const KEYBOARD_HINT = "Enter 전송 · Shift+Enter 줄바꿈";
const TOUCH_HINT = "Enter 줄바꿈 · 전송 버튼으로 보내기";

/** 입력창 최대 높이. 넘으면 입력창 안에서 스크롤한다 */
const MAX_HEIGHT_PX = 200;

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  /** 보낸다. 실제로 보냈으면 true (입력창을 비운다) */
  onSend: (text: string) => boolean;
  onStop: () => void;
  /** 답변을 받는 중 (전송 버튼 → 중지 버튼) */
  isBusy: boolean;
  /** 보낼 수 없는 때 (이전 대화를 불러오는 중 등) */
  isDisabled?: boolean;
  /** 입력창 (되묻기에서 질문을 다시 채운 뒤 포커스용) */
  inputRef?: RefObject<HTMLTextAreaElement | null>;
  /** 빈 입력창 안내. 없으면 기본 문구 */
  placeholder?: string;
  /** 입력창 아래 안내 (지금 보낼 수 없는 이유 등). 없으면 키 사용법 */
  hint?: string;
  /** 쓰던 글을 다른 글로 바꾼 직후 되돌린다. 있으면 입력창 아래 안내 대신 실행 취소 버튼을 보여 준다 */
  onUndoReplace?: () => void;
}

/** 내용에 맞춰 입력창 높이를 맞춘다. MAX_HEIGHT_PX 를 넘으면 그 높이에서 입력창 안을 스크롤한다 */
function fitHeight(ref: RefObject<HTMLTextAreaElement | null>): void {
  const el = ref.current;
  if (!el) {
    return;
  }
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
  el.style.overflowY = el.scrollHeight > MAX_HEIGHT_PX ? "auto" : "hidden";
}

/**
 * 질문 입력: 자동 높이 · Enter 전송(한글 IME 합성 중 제외, 터치 기기는 줄바꿈) · 전송/중지.
 * 계약 한도(MAX_QUESTION_LENGTH)를 넘는 글자는 입력되지 않는다.
 */
export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  isBusy,
  isDisabled = false,
  inputRef,
  placeholder = "질문을 입력하세요",
  hint,
  onUndoReplace,
}: ComposerProps) {
  const isTouch = useMediaQuery(TOUCH_QUERY, false);
  const countId = useId();
  const localRef = useRef<HTMLTextAreaElement>(null);
  const textareaRef = inputRef ?? localRef;
  /** Safari 는 compositionend 가 keydown 보다 먼저 와서 합성을 끝낸 Enter 가 isComposing=false 로 들어온다 */
  const justComposedRef = useRef(false);
  const canSend = !isBusy && !isDisabled && value.trim() !== "";

  useLayoutEffect(() => {
    fitHeight(textareaRef);
  }, [value, textareaRef]);

  // 너비가 바뀌면 줄 수가 달라지므로 높이를 다시 맞춘다 (창 크기 변경 · 화면 회전 · 숨긴 창에서 열었다가 보일 때)
  useEffect(() => {
    const el = textareaRef.current;
    if (!el || typeof ResizeObserver === "undefined") {
      return undefined;
    }
    let width = el.clientWidth;
    const observer = new ResizeObserver(() => {
      // 높이를 바꿔도 이 콜백이 불리므로 너비가 바뀐 때만 맞춘다
      if (el.clientWidth !== width) {
        width = el.clientWidth;
        fitHeight(textareaRef);
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [textareaRef]);

  function submit(): void {
    if (canSend && onSend(value)) {
      onChange("");
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>): void {
    if (e.key !== "Enter" || e.shiftKey || isTouch) {
      return;
    }
    if (e.nativeEvent.isComposing || e.keyCode === IME_KEY_CODE || justComposedRef.current) {
      return;
    }
    e.preventDefault();
    submit();
  }

  function handleCompositionEnd(): void {
    justComposedRef.current = true;
    setTimeout(() => {
      justComposedRef.current = false;
    }, 0);
  }

  return (
    <form
      className="mx-auto w-full max-w-3xl px-4 pb-4"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="flex items-end gap-2 rounded-2xl border border-zinc-300 bg-white p-2 shadow-sm focus-within:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:focus-within:border-zinc-500">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onCompositionEnd={handleCompositionEnd}
          rows={1}
          maxLength={MAX_QUESTION_LENGTH}
          placeholder={placeholder}
          aria-label="질문 입력"
          aria-describedby={countId}
          className="min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-6 outline-none placeholder:text-zinc-400"
        />
        {isBusy ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="답변 중지"
            className="shrink-0 rounded-xl bg-zinc-200 px-4 py-2 text-sm font-medium text-zinc-900 hover:bg-zinc-300 dark:bg-zinc-700 dark:text-zinc-100 dark:hover:bg-zinc-600"
          >
            ■ 중지
          </button>
        ) : (
          <button
            type="submit"
            disabled={!canSend}
            aria-label="질문 전송"
            className="shrink-0 rounded-xl bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            전송
          </button>
        )}
      </div>
      <div className="mt-1.5 flex justify-between gap-4 px-2 text-xs text-zinc-500">
        {onUndoReplace ? (
          <span role="status" className="flex min-w-0 items-center gap-2">
            <span className="truncate">입력하던 글을 바꿨습니다</span>
            <button
              type="button"
              onClick={onUndoReplace}
              className="shrink-0 font-medium text-zinc-700 underline underline-offset-2 dark:text-zinc-300"
            >
              실행 취소
            </button>
          </span>
        ) : (
          <span>{hint ?? (isTouch ? TOUCH_HINT : KEYBOARD_HINT)}</span>
        )}
        <span id={countId} className="shrink-0 tabular-nums">
          {value.length} / {MAX_QUESTION_LENGTH}
        </span>
      </div>
    </form>
  );
}
