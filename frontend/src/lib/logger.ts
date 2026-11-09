// 로그는 이 파일 한 곳을 거친다. 환경 분기도 여기서만 본다.

/**
 * 화면에 알릴 필요는 없지만 원인을 추적할 때 볼 내용(error_code · 요청 실패 원인)을 남긴다.
 * 개발 서버와 운영 화면의 콘솔에 나오고, 테스트 출력에는 나오지 않는다.
 *
 * @param cause 원본 예외처럼 함께 볼 값
 */
export function logWarning(message: string, cause?: unknown): void {
  if (import.meta.env.MODE !== "test") {
    console.warn(message, cause);
  }
}
