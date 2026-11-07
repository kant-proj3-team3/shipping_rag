/// <reference types="vitest/config" />
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
    // ^ 로 시작하는 키는 정규식이다. 문자열 키는 앞부분만 맞아도(/healthz · /sessions) 넘기므로 계약 경로만 넘긴다.
    // 정규식은 쿼리 문자열까지 붙은 주소에 맞춰 보므로 끝을 (\?|$) 로 막는다
    proxy: {
      "^/health(\\?|$)": API_TARGET,
      "^/query(\\?|$)": API_TARGET,
      "^/session/": API_TARGET,
    },
  },
  test: {
    // 기본은 Node 환경. 화면 테스트는 파일 첫 줄 `// @vitest-environment jsdom`
    environment: "node",
  },
});
