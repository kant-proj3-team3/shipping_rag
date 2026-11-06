import { useRef, useState } from "react";

import { RETRIEVAL_MODES, type RetrievalMode } from "./api/types";
import { ChatView } from "./components/ChatView";
import { Composer } from "./components/Composer";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { RetrievalModeSelect } from "./components/RetrievalModeSelect";
import { ServerStatus } from "./components/ServerStatus";
import { useChat } from "./hooks/useChat";
import { useHealth, type HealthState } from "./hooks/useHealth";
import { isAwaitingClarification } from "./lib/chat";
import { DEFAULT_RETRIEVAL_MODE } from "./lib/config";

/** 마지막 답이 되묻기일 때 입력창 안내 */
const CLARIFY_PLACEHOLDER = "빠진 조건을 넣어 질문을 다시 보내 주세요";

/** 업무 Q&A 화면: 머리줄(검색 방식 · 새 대화 · 서버 상태) + 대화 + 입력창 */
export function App() {
  const health = useHealth();
  const chat = useChat();
  const [draft, setDraft] = useState("");
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>(DEFAULT_RETRIEVAL_MODE);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const modes = supportedModesOf(health);
  // 고른 방식을 서버가 지원하지 않으면 지원하는 첫 방식으로 보낸다
  const mode = modes.includes(retrievalMode) ? retrievalMode : (modes[0] ?? retrievalMode);

  function handleClarify(question: string): void {
    setDraft(question);
    inputRef.current?.focus();
  }

  function handleNewChat(): void {
    chat.newChat();
    setDraft("");
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 px-4 py-2 dark:border-zinc-800">
        <h1 className="text-sm font-semibold">해운 업무 Q&amp;A</h1>
        <div className="flex items-center gap-3">
          <RetrievalModeSelect
            value={mode}
            onChange={setRetrievalMode}
            modes={modes}
            disabled={chat.isBusy}
          />
          <button
            type="button"
            onClick={handleNewChat}
            className="rounded-lg border border-zinc-300 px-3 py-1 text-sm hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            새 대화
          </button>
          <ServerStatus state={health} />
        </div>
      </header>
      <main className="flex min-h-0 flex-1 flex-col">
        <ErrorBoundary message="대화를 표시하지 못했습니다. 새로고침해 주세요.">
          <ChatView messages={chat.messages} onClarify={handleClarify} onPickExample={setDraft} />
        </ErrorBoundary>
        <Composer
          value={draft}
          onChange={setDraft}
          onSend={(text) => chat.send(text, mode)}
          onStop={chat.stop}
          isBusy={chat.isBusy}
          inputRef={inputRef}
          placeholder={isAwaitingClarification(chat.messages) ? CLARIFY_PLACEHOLDER : undefined}
        />
      </main>
    </div>
  );
}

/** 서버가 알려 준 검색 방식. 모르면(연결 안 됨 · 빈 목록) 세 방식 전부 */
function supportedModesOf(health: HealthState): readonly RetrievalMode[] {
  if (health.kind === "ok" || health.kind === "index_not_ready") {
    return health.health.supportedModes.length > 0 ? health.health.supportedModes : RETRIEVAL_MODES;
  }
  return RETRIEVAL_MODES;
}
