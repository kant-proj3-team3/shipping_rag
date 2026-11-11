import { useCallback, useRef, useState } from "react";

import { RETRIEVAL_MODES, type RetrievalMode } from "./api/types";
import { ChatView } from "./components/ChatView";
import { Composer } from "./components/Composer";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { RetrievalModeSelect } from "./components/RetrievalModeSelect";
import { SealMascot } from "./components/seal/SealMascot";
import { Sidebar } from "./components/Sidebar";
import { SidebarDrawer } from "./components/SidebarDrawer";
import { ThemeSelect } from "./components/ThemeSelect";
import { useChat } from "./hooks/useChat";
import { useDraft } from "./hooks/useDraft";
import { useDrawer } from "./hooks/useDrawer";
import { useHealth, type HealthState } from "./hooks/useHealth";
import { useTheme } from "./hooks/useTheme";
import { isAwaitingClarification } from "./lib/chat";
import { DEFAULT_RETRIEVAL_MODE } from "./lib/config";

/** 마지막 답이 되묻기일 때 입력창 안내 */
const CLARIFY_PLACEHOLDER = "빠진 조건을 넣어 질문을 다시 보내 주세요";

/** 대화의 서버 세션을 확인하는 동안 입력창 아래 안내 */
const CHECKING_HINT = "이전 대화를 확인하는 중입니다. 잠시 뒤 보낼 수 있습니다";

/** 다른 대화가 답변을 받는 동안 입력창 아래 안내 (요청은 한 번에 하나) */
const BUSY_ELSEWHERE_HINT = "다른 대화의 답변을 받는 중입니다. 끝나면 보낼 수 있습니다";

/** 새 대화 화면의 입력 초안 키 (대화 id 와 겹치지 않는 형식: 세션 id 는 8자 이상이다) */
const NEW_CHAT_DRAFT_KEY = "new";

/** 지금 보낼 수 없는 이유. 보낼 수 있으면 undefined (입력창이 키 사용법을 보여 준다) */
function composerHintOf(isChecking: boolean, isBusyElsewhere: boolean): string | undefined {
  if (isChecking) {
    return CHECKING_HINT;
  }
  return isBusyElsewhere ? BUSY_ELSEWHERE_HINT : undefined;
}

/** 서버가 알려 준 검색 방식. 모르면(연결 안 됨 · 빈 목록) 세 방식 전부 */
function supportedModesOf(health: HealthState): readonly RetrievalMode[] {
  if (health.kind === "ok" || health.kind === "index_not_ready") {
    return health.health.supportedModes.length > 0 ? health.health.supportedModes : RETRIEVAL_MODES;
  }
  return RETRIEVAL_MODES;
}

/** 업무 Q&A 화면: 사이드바(새 대화 · 대화 목록 · 서버 상태) + 머리줄(검색 방식 · 테마) + 대화 + 입력창 */
export function App() {
  const health = useHealth();
  const chat = useChat();
  const { theme, setTheme } = useTheme();
  const {
    isDrawer,
    isOpen: isDrawerOpen,
    open: openDrawer,
    close: closeDrawer,
    panelRef,
    triggerRef,
  } = useDrawer();
  const { draft, setDraft, replaceDraft, canUndoReplace, undoReplace } = useDraft(
    chat.currentId ?? NEW_CHAT_DRAFT_KEY,
  );
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>(DEFAULT_RETRIEVAL_MODE);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const modes = supportedModesOf(health);
  // 고른 방식을 서버가 지원하지 않으면 지원하는 첫 방식으로 보낸다
  const mode = modes.includes(retrievalMode) ? retrievalMode : (modes[0] ?? retrievalMode);
  // 요청은 한 번에 하나: 보고 있는 대화가 받는 중이면 중지 버튼, 다른 대화가 받는 중이면 보내지 않는다
  const isBusyHere = chat.isBusy && chat.activeId === chat.currentId;
  const isBusyElsewhere = chat.isBusy && !isBusyHere;

  // memo 된 대화 화면에 넘기므로 렌더마다 새로 만들지 않는다. 되묻기의 원래 질문 · 예시 질문으로 입력창을 바꾼다
  // (쓰던 글이 있었으면 입력창 아래 실행 취소로 살린다)
  const handleFillDraft = useCallback(
    (text: string) => {
      replaceDraft(text);
      inputRef.current?.focus();
    },
    [replaceDraft],
  );

  function handleUndoReplace(): void {
    undoReplace();
    inputRef.current?.focus();
  }

  function handleNewChat(): void {
    chat.newChat();
    if (isDrawer) {
      closeDrawer();
    } else {
      inputRef.current?.focus();
    }
  }

  // memo 된 대화 목록에 넘기므로 렌더마다 새로 만들지 않는다 (입력할 때마다 목록을 다시 그리지 않게)
  const { select } = chat;
  const handleSelect = useCallback(
    (id: string) => {
      select(id);
      if (isDrawer) {
        closeDrawer();
      }
    },
    [select, isDrawer, closeDrawer],
  );

  return (
    <div className="flex h-full">
      <SidebarDrawer
        isDrawer={isDrawer}
        isOpen={isDrawerOpen}
        onClose={closeDrawer}
        panelRef={panelRef}
      >
        <Sidebar
          health={health}
          conversations={chat.conversations}
          currentId={chat.currentId}
          activeId={chat.activeId}
          onNewChat={handleNewChat}
          onSelect={handleSelect}
          onRemove={chat.remove}
          lastDeleted={chat.lastDeleted}
          onUndoRemove={chat.undoRemove}
          saveResult={chat.saveResult}
        />
      </SidebarDrawer>

      {/* 서랍이 열린 동안 Tab 이 서랍 뒤로 빠지지 않게 한다 */}
      <main className="flex min-w-0 flex-1 flex-col" inert={isDrawerOpen}>
        <header className="flex flex-wrap items-center gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
          {isDrawer ? (
            <button
              ref={triggerRef}
              type="button"
              onClick={openDrawer}
              aria-label="메뉴 열기 (대화 목록 · 서버 상태)"
              aria-expanded={isDrawerOpen}
              aria-controls="sidebar"
              className="-ml-1 rounded-lg px-2 py-1 text-lg leading-none hover:bg-zinc-100 dark:hover:bg-zinc-800"
            >
              ☰
            </button>
          ) : null}
          {/* 제목과 함께 좁은 화면에서는 숨긴다 (머리줄이 두 줄로 늘어난다). 마우스를 올리면 손을 흔들고 반짝이며 눈을 깜박인다.
              32px 로 그리면 선이 굵고 흐려 보여 40px 로 그리고, 물개가 숨는 좁은 화면과 머리줄 높이가 같도록 음수 여백을 둔다 */}
          <SealMascot motion="hover" isSubtle className="-my-1 size-10 shrink-0 max-md:hidden" />
          {/* 좁은 화면에서는 머리줄 자리가 모자라 화면에서만 숨긴다 (스크린 리더는 읽는다) */}
          <h1 className="truncate text-sm font-semibold max-md:sr-only">해운 업무 Q&amp;A</h1>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <RetrievalModeSelect
              value={mode}
              onChange={setRetrievalMode}
              modes={modes}
              disabled={chat.isBusy}
            />
            <ThemeSelect value={theme} onChange={setTheme} />
          </div>
        </header>
        {/* 대화 영역만 경계로 묶어 사이드바 · 입력창은 살려 둔다. 다른 대화로 옮기면 key 로 새로 그린다 */}
        <ErrorBoundary
          key={chat.currentId ?? "new"}
          message="이 대화를 표시하지 못했습니다. 다른 대화를 고르거나 새로고침해 주세요."
        >
          <ChatView
            messages={chat.messages}
            isChecking={chat.isChecking}
            isSessionGone={chat.isSessionGone}
            onClarify={handleFillDraft}
            onPickExample={handleFillDraft}
          />
        </ErrorBoundary>
        <Composer
          value={draft}
          onChange={setDraft}
          onSend={(text) => chat.send(text, mode)}
          onStop={chat.stop}
          isBusy={isBusyHere}
          isDisabled={chat.isChecking || isBusyElsewhere}
          inputRef={inputRef}
          placeholder={isAwaitingClarification(chat.messages) ? CLARIFY_PLACEHOLDER : undefined}
          hint={composerHintOf(chat.isChecking, isBusyElsewhere)}
          onUndoReplace={canUndoReplace ? handleUndoReplace : undefined}
        />
      </main>
    </div>
  );
}
