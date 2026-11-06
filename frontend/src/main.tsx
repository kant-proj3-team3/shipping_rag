import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./index.css";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary message="화면을 표시하지 못했습니다. 새로고침해 주세요.">
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
