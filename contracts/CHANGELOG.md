# 계약 변경 기록

계약(`packages/common`의 types·interfaces·api·errors·entrypoints)이 바뀌면 `CONTRACT_VERSION`을 올리고 같은 버전의 항목을 여기에 쓴다.
항목 제목은 `## [x.y.z]` 형식이어야 한다(`scripts/build_contract_manifest.py`가 확인한다).

## [0.1.1]

세션 이력의 영구 저장(PostgreSQL)과 멀티턴을 반영한다. 타입·필드·경로·HTTP 상태는 바뀌지 않고 **의미만** 바뀐다.
0.x 규칙(삭제·이름 변경 = minor, 호환되는 변경 = patch)에서 필드·경로 변화가 없고 404 조건이 줄어드는 완화이며
`expires_at` 은 이미 `null` 을 허용했으므로 patch 로 올린다(팀이 minor 를 원하면 이 PR 에서 정한다).

- 세션은 만료되지 않는다. `SessionService.get` 은 **한 번도 기록되지 않은 세션**에만 `None`(404 + `session_not_found`)을 돌려준다. `SessionInfo.expires_at` 은 항상 `null` 이다(필드는 그대로).
- 세션 이력의 원본은 영구 저장소(PostgreSQL)이고 Redis 는 조회 캐시다(설계 세부는 구현이 정한다).
- 기록하는 `question` 은 이메일·API 키 모양 문자열을 가린 값이다. 대화 복원 때 입력 원문과 다를 수 있다.
- 멀티턴: `QAService` 는 `request.session_id` 가 있으면 같은 세션의 이전 turn 을 답변에 반영한다. 반영할 turn 수와 방식은 구현이 정하고, 이력을 쓴 요청은 캐시 키에 이력을 반영하거나 캐시를 우회한다(기존 규칙을 확정으로 바꿈).
- 예시: `session_info.json` 의 `expires_at` 을 `null` 로, `session_not_found.json` 의 문구를 "세션을 찾을 수 없습니다." 로.
- 소비자 영향: 프론트엔드의 404 처리는 그대로 동작한다. "서버에서 만료된 대화입니다" 안내(`ChatView.tsx`, `useChat.ts`, `lib/session.ts`)는 영구 저장 뒤에 사실과 맞지 않게 되므로 frontend 담당이 고친다(이 PR 범위 밖). 모듈 선언(`[tool.rag-contract] version`)은 0.1.0 그대로여도 경고만 나며 각자 rebase 때 올린다.

## [0.1.0]

최초 계약.

- 타입: 청킹 산출물(`Chunk`, `IndexManifest`), 골든 데이터셋(`GoldenItem`), 검색(`RetrievalRequest`/`RetrievalResult`/`RetrievalReport`), API(`QueryRequest`/`QueryResponse`/`SessionInfo`/`HealthResponse`/`ApiError`), 답변 평가(`AnswerEvaluation`).
- 인터페이스: `Embedder`, `Indexer`, `GoldenDatasetProvider`, `Retriever`, `RetrievalEvaluator`, `QAService`, `SessionService`, `AnswerEvaluator`.
- 진입점 시그니처: `create_embedder`, `create_indexer`, `create_golden_provider`, `create_retriever`, `create_retrieval_evaluator`, `create_qa_service`, `create_session_service`, `create_answer_evaluator`, `create_router`.
- HTTP: `/health`, `/query`, `/session/{session_id}`, `ERROR_HTTP_STATUS` 매핑.
- `Retriever.index -> IndexManifest`: 생성 시 주입받은 manifest 를 그대로 노출한다. 평가기(보고서의 인덱스 신원)와 백엔드(캐시 키의 `index_name`+`embedder_id`)가 읽는다.
- `RetrievalEvaluator.evaluate(items, mode, k, unit, golden_fingerprint=None)`: 호출자가 `GoldenDatasetProvider.fingerprint` 값을 넘기면 보고서의 `golden_fingerprint` 에 남긴다(선택 인자).
- 비동기 규칙 정리: 실시간 경로(`retrieve`, `answer`, `get`)와 이를 동시에 호출하는 평가기(`evaluate`)는 async, 색인·골든 로딩은 sync.
