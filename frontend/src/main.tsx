import "./lib/installErrorLogging";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./index.css";
import { createHttpApiClient } from "./api/httpClient";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { API_BASE, READ_TIMEOUT_MS } from "./lib/config";
import { createBrowserStorage } from "./lib/storage";
import { ApiProvider } from "./providers/ApiProvider";
import { StorageProvider } from "./providers/StorageProvider";

// 앱 전체가 쓰는 API 클라이언트 · 저장소 · 서버 데이터 캐시는 여기서 한 번만 만든다
const api = createHttpApiClient({ baseUrl: API_BASE, readTimeoutMs: READ_TIMEOUT_MS });
const storage = createBrowserStorage();
const queryClient = new QueryClient();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary message="화면을 표시하지 못했습니다. 새로고침해 주세요.">
      <QueryClientProvider client={queryClient}>
        <StorageProvider storage={storage}>
          <ApiProvider client={api}>
            <App />
          </ApiProvider>
        </StorageProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
