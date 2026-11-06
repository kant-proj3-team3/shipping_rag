import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./index.css";
import { createHttpApiClient } from "./api/httpClient";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { API_BASE, HEALTH_TIMEOUT_MS } from "./lib/config";
import { ApiProvider } from "./providers/ApiProvider";

// 앱 전체가 쓰는 API 클라이언트는 여기서 한 번만 만든다
const api = createHttpApiClient({ baseUrl: API_BASE, healthTimeoutMs: HEALTH_TIMEOUT_MS });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary message="화면을 표시하지 못했습니다. 새로고침해 주세요.">
      <ApiProvider client={api}>
        <App />
      </ApiProvider>
    </ErrorBoundary>
  </StrictMode>,
);
