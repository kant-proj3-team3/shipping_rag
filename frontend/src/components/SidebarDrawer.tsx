import type { ReactNode, RefObject } from "react";

const DRAWER_PANEL_CLASS =
  "fixed inset-y-0 left-0 z-40 flex shadow-xl transition-transform duration-200 motion-reduce:transition-none";

interface SidebarDrawerProps {
  /** 좁은 화면이라 서랍으로 동작하는지. false 면 그냥 자리를 차지한다 */
  isDrawer: boolean;
  isOpen: boolean;
  onClose: () => void;
  panelRef: RefObject<HTMLDivElement | null>;
  children: ReactNode;
}

/** 사이드바 자리: 넓은 화면에서는 그대로, 좁은 화면에서는 배경과 함께 서랍으로 연다 */
export function SidebarDrawer({
  isDrawer,
  isOpen,
  onClose,
  panelRef,
  children,
}: SidebarDrawerProps) {
  const isClosedDrawer = isDrawer && !isOpen;
  return (
    <>
      {isOpen ? (
        // 키보드로는 Esc 로 닫는다 (useDrawer). 배경은 마우스 · 터치용이라 포커스를 받지 않는다
        <div
          className="fixed inset-0 z-30 bg-black/40"
          onClick={onClose}
          aria-hidden="true"
          data-testid="drawer-backdrop"
        />
      ) : null}
      <div
        ref={panelRef}
        id="sidebar"
        className={
          isDrawer
            ? `${DRAWER_PANEL_CLASS} ${isOpen ? "translate-x-0" : "-translate-x-full"}`
            : "flex"
        }
        inert={isClosedDrawer}
        role={isDrawer ? "dialog" : undefined}
        aria-modal={isOpen || undefined}
        aria-label={isDrawer ? "메뉴" : undefined}
      >
        {children}
      </div>
    </>
  );
}
