// 설정값은 이 파일 한 곳에 모은다.

import { QUERY_REQUEST_QUESTION_MAX_LENGTH, type RetrievalMode } from "../api/types";

/** API 주소. 비우면 같은 주소의 상대 경로(개발 중에는 Vite 프록시)로 보낸다 */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "";

/** 읽기 요청(/health · /session) 응답 대기 한도 (넘으면 서버에 닿지 못한 것으로 본다) */
export const READ_TIMEOUT_MS = 5_000;

/** /health 확인 주기 */
export const HEALTH_INTERVAL_MS = 30_000;

/** 답변 대기 표시를 이만큼 기다린 뒤에 보여 준다. 그 안에 답이 오면 그리지 않는다 (번쩍임 방지) */
export const PENDING_SHOW_DELAY_MS = 300;

/** 답변 대기 표시가 한번 보이면 최소 이만큼은 둔다. 나타나자마자 사라지지 않게 한다 */
export const PENDING_MIN_VISIBLE_MS = 500;

/** 처음 고른 검색 방식. 세 방식 중 품질 기대가 가장 높은 방식이다 */
export const DEFAULT_RETRIEVAL_MODE: RetrievalMode = "hybrid_rerank";

/** 대화 목록 저장소 키 */
export const HISTORY_STORAGE_KEY = "shipping-rag:conversations:v1";

/** 보고 있던 대화 저장소 키. 새로고침하면 이 대화를 다시 연다 */
export const CURRENT_STORAGE_KEY = "shipping-rag:current:v1";

/** 고른 화면 테마 저장소 키. index.html 의 인라인 스크립트도 같은 키를 읽는다 */
export const THEME_STORAGE_KEY = "shipping-rag:theme";

/** 대화 보관 한도 (최신순). 대화 하나가 수 KB 라 localStorage 한도(약 5MB) 안에 넉넉하다 */
export const MAX_CONVERSATIONS = 200;

/**
 * 질문 최대 글자 수. 계약(QueryRequest.question 의 maxLength)에서 생성한 값이다.
 * 브라우저 maxLength 는 UTF-16 단위라 이모지를 2자로 센다. 서버(Python len)보다 엄격한 쪽이라 길이 초과 422 를 받지 않는다
 */
export const MAX_QUESTION_LENGTH = QUERY_REQUEST_QUESTION_MAX_LENGTH;
