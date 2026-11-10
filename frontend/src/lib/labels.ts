// 화면 표시 이름은 이 파일 한 곳에 모은다.

import type { SaveResult } from "./history";
import type { RequestErrorCode } from "../api/client";
import type { RetrievalMode } from "../api/types";

/** 화면 테마: 시스템 설정을 따르기 · 라이트 · 다크 */
export const THEMES = ["system", "light", "dark"] as const;
/** THEMES 의 값 하나 */
export type Theme = (typeof THEMES)[number];

/** 화면 테마 표시 이름 */
export const THEME_NAMES: Record<Theme, string> = {
  system: "시스템",
  light: "라이트",
  dark: "다크",
};

/** 검색 방식 표시 이름 */
export const RETRIEVAL_MODE_NAMES: Record<RetrievalMode, string> = {
  naive: "Naive",
  hybrid: "하이브리드",
  hybrid_rerank: "하이브리드 + 리랭킹",
};

/** 대화 목록을 다 저장하지 못했을 때 사이드바 안내 */
export const SAVE_WARNING_TEXT: Record<Exclude<SaveResult, "saved">, string> = {
  trimmed: "저장 공간이 부족해 오래된 대화 일부를 저장하지 못했습니다",
  failed: "대화 목록을 저장하지 못했습니다 (브라우저 저장소를 쓸 수 없음)",
};

/** 서버가 오류로 답했는데 사용자용 문구가 비어 있을 때의 안내 (계약은 빈 문구도 허용한다) */
export const UNKNOWN_ERROR_TEXT = "알 수 없는 오류가 발생했습니다. 다시 시도해 주세요.";

/**
 * 응답을 받지 못한 이유별 사용자용 안내. 코드 자체는 로그용이라 화면에 보이지 않는다.
 * aborted 는 오류가 아니라 중지로 그려 안내가 없다
 */
export const REQUEST_ERROR_TEXT: Record<Exclude<RequestErrorCode, "aborted">, string> = {
  network: "서버에 연결하지 못했습니다. 서버 상태를 확인한 뒤 다시 시도해 주세요.",
  bad_response: "서버 응답을 읽지 못했습니다. 다시 시도해 주세요.",
  invalid_question: "질문을 확인해 주세요 (비어 있거나 너무 깁니다).",
  invalid_retrieval_mode: "검색 방식이 올바르지 않습니다. 다른 방식을 골라 다시 보내 주세요.",
  invalid_session_id: "대화 정보가 올바르지 않습니다. 새 대화로 다시 시도해 주세요.",
  invalid_request: "요청을 처리하지 못했습니다. 다시 시도해 주세요.",
};
