// 설정값은 이 파일 한 곳에 모은다.

import type { RetrievalMode } from "../api/types";

/** API 주소. 비우면 같은 주소의 상대 경로(개발 중에는 Vite 프록시)로 보낸다 */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "";

/** /health 응답 대기 한도 (넘으면 서버에 닿지 못한 것으로 본다) */
export const HEALTH_TIMEOUT_MS = 5_000;

/** /health 확인 주기 */
export const HEALTH_INTERVAL_MS = 30_000;

/** 처음 고른 검색 방식. 세 방식 중 품질 기대가 가장 높은 방식이다 */
export const DEFAULT_RETRIEVAL_MODE: RetrievalMode = "hybrid_rerank";

/** 대화 세션 id 를 남기는 저장소 키. 새로고침하면 이 세션의 기록을 서버에서 다시 불러온다 */
export const SESSION_STORAGE_KEY = "shipping-rag:session:v1";

/**
 * 질문 최대 글자 수. 계약(QueryRequest.question 의 maxLength)과 같다.
 * 브라우저 maxLength 는 UTF-16 단위라 이모지를 2자로 센다. 서버(Python len)보다 엄격한 쪽이라 길이 초과 422 를 받지 않는다
 */
export const MAX_QUESTION_LENGTH = 500;
