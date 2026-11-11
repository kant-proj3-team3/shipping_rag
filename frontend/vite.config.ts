/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// RAG Q&A API (개발 중에는 프록시로 붙여 CORS 를 피한다)
// Windows에서 localhost는 IPv6를 먼저 시도해 요청마다 약 2초 늦으므로 127.0.0.1로 지정한다.
const API_TARGET = "http://127.0.0.1:8000";

// 개발 서버에서 /query 를 이만큼(ms) 늦춘다. 목업 api 는 바로 답해서 답을 기다리는 화면(물개)을 볼 수 없어 확인할 때만 켠다.
// 셸 환경 변수로 준다 (예: QUERY_DELAY_MS=3000 npm run dev, PowerShell 은 $env:QUERY_DELAY_MS=3000; npm run dev). 없으면 늦추지 않는다
const QUERY_DELAY_MS = Number(process.env.QUERY_DELAY_MS ?? 0);

/** 개발 서버에서 /query 요청을 ms 만큼 늦게 api 로 넘긴다. 0 이하면 켜지 않는다 (빌드 결과 · nginx 에는 영향이 없다) */
function delayQuery(ms: number): Plugin {
  return {
    name: "delay-query",
    apply: (_config, { command }) => command === "serve" && ms > 0,
    configureServer(server) {
      // 여기서 바로 붙인 미들웨어는 Vite 의 프록시보다 먼저 돈다
      server.middlewares.use((req, _res, next) => {
        if (/^\/query(\?|$)/.test(req.url ?? "")) {
          setTimeout(next, ms);
          return;
        }
        next();
      });
    },
  };
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), delayQuery(QUERY_DELAY_MS)],
  build: {
    // 로그 서버가 스택을 원본 위치로 바꿀 때 쓴다. hidden 은 JS 에 소스맵 주소를 남기지 않고, Dockerfile 이 파일을 web 이미지 밖으로 옮긴다
    sourcemap: "hidden",
  },
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
