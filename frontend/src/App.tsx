import { useState } from "react";

import { Composer } from "./components/Composer";

/** 업무 Q&A 화면. 지금은 질문 입력창만 있다 */
export function App() {
  const [draft, setDraft] = useState("");

  return (
    <main className="flex h-full items-center justify-center">
      <Composer value={draft} onChange={setDraft} />
    </main>
  );
}
