import { useCallback, useRef, useState, type RefObject } from "react";

import { useStorage } from "./useStorage";
import { useStorageChange } from "./useStorageChange";
import { HISTORY_STORAGE_KEY } from "../lib/config";
import {
  loadHistory,
  mergeFromOtherTab,
  mergeStoredHistory,
  saveHistory,
  type LoadedHistory,
  type SaveResult,
} from "../lib/history";

/** useChatHistory 가 돌려주는 목록 상태와 동작 */
export interface UseChatHistoryResult {
  /** 화면에 그리는 목록 */
  history: LoadedHistory;
  /** 가장 최근 목록. 핸들러 · 응답 콜백이 다시 그리기를 기다리지 않고 읽는다 */
  historyRef: RefObject<LoadedHistory>;
  /** 마지막 저장 결과 */
  saveResult: SaveResult;
  /**
   * 목록을 바꾼다.
   *
   * @param shouldSave 저장소에도 바로 쓴다 (다른 탭의 변경을 먼저 합친다). 보고 있는 대화만 바꿀 때는 쓰지 않는다 (그건 따로 남긴다)
   */
  updateHistory: (change: (history: LoadedHistory) => LoadedHistory, shouldSave?: boolean) => void;
}

/**
 * 대화 목록을 저장소에서 불러와 들고 있고, 바꿀 때 저장한다.
 * 다른 탭이 저장한 목록은 storage 이벤트로 받아 합친다. 보고 있는 대화는 useChat 이 남긴다
 */
export function useChatHistory(): UseChatHistoryResult {
  const storage = useStorage();
  const [history, setHistory] = useState<LoadedHistory>(() => loadHistory(storage));
  const [saveResult, setSaveResult] = useState<SaveResult>("saved");
  const historyRef = useRef(history);
  // 저장에 실패한 동안에는 저장본에 없는 대화가 곧 이 탭의 새 대화라, 합치면 지운 것으로 보게 된다
  const lastSaveRef = useRef<SaveResult>("saved");

  // 세션 확인 · storage 이벤트 effect 의 의존성이라 렌더마다 새로 만들지 않는다
  const updateHistory = useCallback<UseChatHistoryResult["updateHistory"]>(
    (change, shouldSave = false) => {
      const base =
        shouldSave && lastSaveRef.current !== "failed"
          ? mergeStoredHistory(storage, historyRef.current)
          : historyRef.current;
      const next = change(base);
      historyRef.current = next;
      setHistory(next);
      if (shouldSave) {
        const result = saveHistory(storage, next.conversations);
        lastSaveRef.current = result;
        // 줄여서 저장하면 다음 저장은 성공한다. 오래된 대화가 빠졌다는 안내가 바로 사라지지 않게 남겨 둔다
        setSaveResult((prev) => (prev === "trimmed" && result === "saved" ? prev : result));
      }
    },
    [storage],
  );

  // 다른 탭이 목록을 저장하면 합친다. 합치지 않으면 이 탭이 다음에 저장할 때 다른 탭의 대화를 덮어써 지운다
  const mergeOtherTab = useCallback(() => {
    const { conversations } = loadHistory(storage);
    // 저장에 실패한 동안에는 저장본에 없는 대화가 이 탭에서만 있는 대화일 수 있어 지운 것으로 보지 않는다
    const isUnsaved = lastSaveRef.current === "failed";
    updateHistory((h) => mergeFromOtherTab(h, conversations, isUnsaved));
  }, [storage, updateHistory]);
  useStorageChange(HISTORY_STORAGE_KEY, mergeOtherTab);

  return { history, historyRef, saveResult, updateHistory };
}
