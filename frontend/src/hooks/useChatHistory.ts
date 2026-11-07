import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { useStorage } from "./useStorage";
import { HISTORY_STORAGE_KEY } from "../lib/config";
import { loadHistory, mergeFromOtherTab, saveHistory, type LoadedHistory } from "../lib/history";

/** useChatHistory 가 돌려주는 목록 상태와 동작 */
export interface UseChatHistoryResult {
  /** 화면에 그리는 목록 */
  history: LoadedHistory;
  /** 가장 최근 목록. 핸들러 · 응답 콜백이 다시 그리기를 기다리지 않고 읽는다 */
  historyRef: RefObject<LoadedHistory>;
  /** 마지막 저장이 성공했는지 */
  isStorageOk: boolean;
  /**
   * 목록을 바꾼다.
   *
   * @param shouldSave 저장소에도 바로 쓴다. 보고 있는 대화만 바꿀 때는 쓰지 않는다 (그건 따로 남긴다)
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
  const [isStorageOk, setIsStorageOk] = useState(true);
  const historyRef = useRef(history);

  // 세션 확인 · storage 이벤트 effect 의 의존성이라 렌더마다 새로 만들지 않는다
  const updateHistory = useCallback<UseChatHistoryResult["updateHistory"]>(
    (change, shouldSave = false) => {
      const next = change(historyRef.current);
      historyRef.current = next;
      setHistory(next);
      if (shouldSave) {
        setIsStorageOk(saveHistory(storage, next.conversations));
      }
    },
    [storage],
  );

  // 다른 탭이 목록을 저장하면 합친다. 합치지 않으면 이 탭이 다음에 저장할 때 다른 탭의 대화를 덮어써 지운다
  useEffect(() => {
    function handleStorage(e: StorageEvent): void {
      // key 가 null 이면 다른 탭이 저장소를 통째로 비웠다
      if (e.key === HISTORY_STORAGE_KEY || e.key === null) {
        const { conversations } = loadHistory(storage);
        updateHistory((h) => mergeFromOtherTab(h, conversations));
      }
    }
    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, [storage, updateHistory]);

  return { history, historyRef, isStorageOk, updateHistory };
}
