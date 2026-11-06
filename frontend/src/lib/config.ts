// 설정값은 이 파일 한 곳에 모은다.

/** API 주소. 비우면 같은 주소의 상대 경로(개발 중에는 Vite 프록시)로 보낸다 */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "";

/** /health 응답 대기 한도 (넘으면 서버에 닿지 못한 것으로 본다) */
export const HEALTH_TIMEOUT_MS = 5_000;

/**
 * 질문 최대 글자 수. 계약(QueryRequest.question 의 maxLength)과 같다.
 * 브라우저 maxLength 는 UTF-16 단위라 이모지를 2자로 센다. 서버(Python len)보다 엄격한 쪽이라 길이 초과 422 를 받지 않는다
 */
export const MAX_QUESTION_LENGTH = 500;
