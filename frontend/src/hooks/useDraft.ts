import { useCallback, useState } from "react";

/** useDraft 가 돌려주는 입력 초안과 동작 */
export interface UseDraftResult {
  /** 지금 대화의 입력 초안 */
  draft: string;
  /** 지금 대화의 초안을 바꾼다 */
  setDraft: (text: string) => void;
  /** 입력창이 비어 있을 때만 채운다 (쓰던 글을 지우지 않게) */
  fillIfEmpty: (text: string) => void;
}

/**
 * 대화별 입력 초안. 대화를 옮겨도 쓰던 글이 다른 대화로 보내지지 않고, 돌아오면 그대로 있다.
 *
 * @param key 지금 대화를 가리키는 값
 */
export function useDraft(key: string): UseDraftResult {
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  // memo 된 대화 화면에 넘기는 핸들러의 의존성이라 대화가 바뀔 때만 새로 만든다
  const setDraft = useCallback(
    (text: string) => setDrafts((prev) => ({ ...prev, [key]: text })),
    [key],
  );
  const fillIfEmpty = useCallback(
    (text: string) =>
      setDrafts((prev) => ((prev[key] ?? "").trim() === "" ? { ...prev, [key]: text } : prev)),
    [key],
  );

  return { draft: drafts[key] ?? "", setDraft, fillIfEmpty };
}
