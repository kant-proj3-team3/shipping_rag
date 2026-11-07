import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { flushSync } from "react-dom";

import { useMediaQuery } from "./useMediaQuery";

/** 이 너비 이상이면 사이드바가 자리를 차지하고, 미만이면 서랍(drawer)으로 연다. Tailwind md 와 같다 */
const DESKTOP_QUERY = "(min-width: 768px)";

/** useDrawer 가 돌려주는 서랍 상태와 동작 */
export interface UseDrawerResult {
  /** 좁은 화면이라 사이드바가 서랍으로 동작하는지 */
  isDrawer: boolean;
  /** 서랍이 열려 있는지 (넓은 화면에서는 항상 false) */
  isOpen: boolean;
  open: () => void;
  /** 닫는다. 서랍 안에 포커스가 있었으면 여는 버튼으로 돌려준다 */
  close: () => void;
  /** 서랍 요소 */
  panelRef: RefObject<HTMLDivElement | null>;
  /** 서랍을 여는 버튼 */
  triggerRef: RefObject<HTMLButtonElement | null>;
}

/** 좁은 화면의 사이드바 서랍: 열면 첫 버튼으로 포커스, Esc 로 닫기 */
export function useDrawer(): UseDrawerResult {
  const isDrawer = !useMediaQuery(DESKTOP_QUERY, true);
  const [isOpenState, setIsOpenState] = useState(false);
  // 넓은 화면이 되는 순간에도 닫힌 것으로 본다 (연 상태는 아래 effect 가 닫는다)
  const isOpen = isDrawer && isOpenState;
  const panelRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // 아래 effect 의 의존성이라 렌더마다 새로 만들지 않는다 (새로 만들면 열린 동안 포커스를 다시 옮긴다)
  const close = useCallback(() => {
    const hasFocus = panelRef.current?.contains(document.activeElement) ?? false;
    // 여는 버튼은 서랍이 열린 동안 inert 인 <main> 안에 있어 포커스를 받지 못한다. 먼저 닫아 inert 를 푼다
    flushSync(() => setIsOpenState(false));
    if (hasFocus) {
      triggerRef.current?.focus();
    }
  }, []);

  function open(): void {
    setIsOpenState(true);
  }

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }
    panelRef.current?.querySelector<HTMLElement>("button")?.focus();
    function handleKeyDown(e: KeyboardEvent): void {
      if (e.key === "Escape") {
        close();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, close]);

  // 열어 둔 채 넓은 화면이 되면 닫는다. 그대로 두면 다시 좁아질 때 서랍이 저절로 열린다.
  // isOpen 은 넓어지는 순간 false 가 되어 위 effect 가 먼저 정리되므로, 연 상태(isOpenState)를 기준으로 듣는다
  useEffect(() => {
    if (!isOpenState || typeof window.matchMedia !== "function") {
      return undefined;
    }
    const media = window.matchMedia(DESKTOP_QUERY);
    function handleChange(e: MediaQueryListEvent): void {
      if (e.matches) {
        setIsOpenState(false);
      }
    }
    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, [isOpenState]);

  return { isDrawer, isOpen, open, close, panelRef, triggerRef };
}
