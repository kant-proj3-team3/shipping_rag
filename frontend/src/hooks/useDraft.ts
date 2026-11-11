import { useCallback, useReducer } from "react";

const INITIAL_STATE: DraftState = { drafts: {}, replacement: undefined };

/** useDraft 가 돌려주는 입력 초안과 동작 */
export interface UseDraftResult {
  /** 지금 대화의 입력 초안 */
  draft: string;
  /** 지금 대화의 초안을 바꾼다 */
  setDraft: (text: string) => void;
  /** 입력창을 text 로 바꾼다 (예시 질문 · 되묻기의 원래 질문). 쓰던 글이 있었으면 undoReplace 로 되돌릴 수 있다 */
  replaceDraft: (text: string) => void;
  /** replaceDraft 전에 쓰던 글로 되돌릴 수 있는지. 바꾼 뒤 입력창에 손대지 않은 동안만 그렇다 (실행 취소 안내를 보여 줄지 정한다) */
  canUndoReplace: boolean;
  /** replaceDraft 전에 쓰던 글로 되돌린다 */
  undoReplace: () => void;
}

/** replaceDraft 로 바꾼 기록: 어느 대화에서 무엇을 무엇으로 바꿨나 */
interface Replacement {
  key: string;
  before: string;
  after: string;
}

interface DraftState {
  /** 대화 키 → 입력 초안 */
  drafts: Record<string, string>;
  /** 마지막으로 바꾼 기록. 되돌릴 쓰던 글이 없으면 undefined */
  replacement: Replacement | undefined;
}

type DraftAction =
  | { type: "set"; key: string; text: string }
  | { type: "replace"; key: string; text: string }
  | { type: "undo"; key: string };

// 그 대화의 입력 초안. 아직 쓰지 않았으면 빈 글이다
function draftOf(state: DraftState, key: string): string {
  return state.drafts[key] ?? "";
}

// 바꾼 뒤 입력창에 손대지 않았으면 그 대화의 바꾼 기록이다
function replacementOf(state: DraftState, key: string): Replacement | undefined {
  const { replacement } = state;
  return replacement?.key === key && draftOf(state, key) === replacement.after
    ? replacement
    : undefined;
}

function draftReducer(state: DraftState, action: DraftAction): DraftState {
  switch (action.type) {
    case "set":
      return { ...state, drafts: { ...state.drafts, [action.key]: action.text } };
    case "replace": {
      const before = draftOf(state, action.key);
      // 쓰던 글이 있고 다른 글로 바뀔 때만 되돌릴 수 있게 남긴다
      const canUndo = before.trim() !== "" && before !== action.text;
      return {
        drafts: { ...state.drafts, [action.key]: action.text },
        replacement: canUndo ? { key: action.key, before, after: action.text } : undefined,
      };
    }
    case "undo": {
      const replacement = replacementOf(state, action.key);
      if (replacement === undefined) {
        return state;
      }
      return {
        drafts: { ...state.drafts, [action.key]: replacement.before },
        replacement: undefined,
      };
    }
  }
}

/**
 * 대화별 입력 초안. 대화를 옮겨도 쓰던 글이 다른 대화로 보내지지 않고, 돌아오면 그대로 있다.
 *
 * @param key 지금 대화를 가리키는 값
 */
export function useDraft(key: string): UseDraftResult {
  const [state, dispatch] = useReducer(draftReducer, INITIAL_STATE);

  // memo 된 대화 화면에 넘기는 핸들러의 의존성이라 대화가 바뀔 때만 새로 만든다
  const setDraft = useCallback((text: string) => dispatch({ type: "set", key, text }), [key]);
  const replaceDraft = useCallback(
    (text: string) => dispatch({ type: "replace", key, text }),
    [key],
  );
  const undoReplace = useCallback(() => dispatch({ type: "undo", key }), [key]);

  return {
    draft: draftOf(state, key),
    setDraft,
    replaceDraft,
    canUndoReplace: replacementOf(state, key) !== undefined,
    undoReplace,
  };
}
