// 계약(openapi.json)에 아직 description 이 없는 컴포넌트 · 필드의 설명. gen-schemas.mjs 가 생성 타입의 JSDoc 으로 넣는다.
// 키는 "컴포넌트" 또는 "컴포넌트.필드"(서버 형식 이름)다. 없는 컴포넌트 · 필드를 가리키면 생성이 멈춘다.
// 백엔드가 계약에 description 을 넣으면 그 항목은 여기서 지운다 (둘 다 있으면 생성이 멈추고 지울 항목을 알려 준다).

/** 계약에 아직 없는 설명 */
export const DESCRIPTIONS = {
  HealthResponse: "GET /health 응답",
  "HealthResponse.index_ready": "false 면 서버는 떴지만 검색 인덱스가 준비되지 않았다",
  "HealthResponse.supported_modes": "서버가 지원하는 검색 방식. 비어 있으면 알려 주지 않은 것",

  Citation: "출처 한 건",
  "Citation.source_id": "요청 안에서만 유효하다. 화면에 보이지 않는다",
  "Citation.file_name": "문서명 (예: IS12.pdf)",
  "Citation.page": "쪽 번호 (첫 쪽 = 1)",

  QueryMeta: "응답 부가 정보. 모르는 값은 0 이 아니라 null 이다",
  "QueryMeta.retrieval_mode": "실제로 쓴 검색 방식",
  "QueryMeta.cache_hit": "캐시에서 꺼낸 응답",

  QueryResponse: "POST /query 응답. 오류 상태 코드(status=error)도 이 모양이다",
  "QueryResponse.answer":
    "결론. needs_clarification 이면 되묻는 문장, abstained 면 보류 이유, error 면 서버의 사용자용 문구",
  "QueryResponse.reason": "근거",
  "QueryResponse.citations": "answered 면 1개 이상",
  "QueryResponse.error_code":
    "status=error 일 때만, 그리고 반드시 있다. 로그용이며 화면에 보이지 않는다",

  "SessionTurn.asked_at": "질문한 시각",

  "SessionInfo.expires_at": "만료 예정 시각",
  "SessionInfo.turn_count": "세션 전체 turn 수. turns 는 그중 최근 일부일 수 있다",
  "SessionInfo.turns": "오래된 것 → 최신 순",

  "QueryRequest.question": "질문 원문 (공백만은 안 된다)",
  "QueryRequest.session_id": "대화 세션 id. 같은 대화의 질문은 같은 id 로 보낸다",
};
