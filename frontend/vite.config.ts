/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// RAG Q&A API (개발 중에는 프록시로 붙여 CORS 를 피한다)
// Windows에서 localhost는 IPv6를 먼저 시도해 요청마다 약 2초 늦으므로 127.0.0.1로 지정한다.
const API_TARGET = "http://127.0.0.1:8000";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/health": API_TARGET,
      "/query": API_TARGET,
      "/session": API_TARGET,
    },
    fs: {
      // 목업이 저장소 루트의 contracts/examples/*.json 을 그대로 읽는다 (Vite 는 기본적으로 프로젝트 밖 파일을 막는다)
      allow: [
        fileURLToPath(new URL(".", import.meta.url)),
        fileURLToPath(new URL("../contracts", import.meta.url)),
      ],
    },
  },
  test: {
    // 기본은 Node 환경. 화면 테스트는 파일 첫 줄 `// @vitest-environment jsdom`
    environment: "node",
  },
});
