// 로그 서버 진입점. Node 가 TypeScript 를 그대로 실행하므로 빌드 단계가 없다.

import { createApp } from "./app.ts";
import { createLogSink } from "./logger.ts";
import { createStackMapper } from "./sourceMaps.ts";

const PORT = 3001; // nginx.conf 의 log-server 주소와 같다
const DEFAULT_LOG_DIR = "logs";
// 날짜별 로그의 하루 양. 14일 보관(logger.ts)과 합쳐 280MB, 넘침 파일까지 합쳐 전체 380MB 안쪽이다
const DAILY_LOG_BYTES = 20 * 1024 * 1024;

const sink = createLogSink(process.env.LOG_DIR ?? DEFAULT_LOG_DIR, DAILY_LOG_BYTES);
const app = createApp(sink, createStackMapper(process.env.SOURCE_MAP_DIR, sink));

const server = app.listen(PORT, (error) => {
  if (error) {
    throw error;
  }
  sink.write({ level: "info", message: `로그 서버 시작 (포트 ${PORT})` });
});

// 컨테이너에서 Node 는 PID 1 이라 처리기가 없으면 docker stop 신호에 끝나지 않는다.
// 서버만 닫으면 밀린 로그를 마저 쓰고 프로세스가 스스로 끝난다 (쓰기가 밀린 중에 logger.end 를 부르면 write after end 로 죽는다)
function shutdown(): void {
  server.close();
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
