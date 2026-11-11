// 아무도 잡지 않은 오류를 로그로 남기도록 창 이벤트를 듣는다.
// 다른 모듈을 읽는 중에 난 오류도 잡으려고 main.tsx 가 가장 먼저 import 한다.

import { logUnexpectedError } from "./logger";

window.addEventListener("error", (event) => {
  // error 가 없는 이벤트는 ResizeObserver 알림처럼 코드 오류가 아니다. Error 가 아닌 값을 던진 경우는 내용 없이 발생만 남긴다
  if (event.error != null) {
    logUnexpectedError("잡히지 않은 오류가 났다", event.error);
  }
});

window.addEventListener("unhandledrejection", (event) => {
  logUnexpectedError("처리하지 않은 Promise 거부가 났다", event.reason);
});
