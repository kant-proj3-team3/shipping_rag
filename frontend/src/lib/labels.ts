// 화면 표시 이름은 이 파일 한 곳에 모은다.

import type { RetrievalMode } from "../api/types";

/** 검색 방식 표시 이름 */
export const RETRIEVAL_MODE_NAMES: Record<RetrievalMode, string> = {
  naive: "Naive",
  hybrid: "하이브리드",
  hybrid_rerank: "하이브리드 + 리랭킹",
};
