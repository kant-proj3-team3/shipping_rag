# 계약 변경 기록

계약(`packages/common`의 types·interfaces·api·errors·entrypoints)이 바뀌면 `CONTRACT_VERSION`을 올리고 같은 버전의 항목을 여기에 쓴다.
항목 제목은 `## [x.y.z]` 형식이어야 한다(`scripts/build_contract_manifest.py`가 확인한다).

## [0.1.0]

최초 계약.

- 타입: 청킹 산출물(`Chunk`, `IndexManifest`), 골든 데이터셋(`GoldenItem`), 검색(`RetrievalRequest`/`RetrievalResult`/`RetrievalReport`), API(`QueryRequest`/`QueryResponse`/`SessionInfo`/`HealthResponse`/`ApiError`), 답변 평가(`AnswerEvaluation`).
- 인터페이스: `Embedder`, `Indexer`, `GoldenDatasetProvider`, `Retriever`, `RetrievalEvaluator`, `QAService`, `SessionService`, `AnswerEvaluator`.
- 진입점 시그니처: `create_embedder`, `create_indexer`, `create_golden_provider`, `create_retriever`, `create_retrieval_evaluator`, `create_qa_service`, `create_session_service`, `create_answer_evaluator`, `create_router`.
- HTTP: `/health`, `/query`, `/session/{session_id}`, `ERROR_HTTP_STATUS` 매핑.
- `Retriever.index -> IndexManifest`: 생성 시 주입받은 manifest 를 그대로 노출한다. 평가기(보고서의 인덱스 신원)와 백엔드(캐시 키의 `index_name`+`embedder_id`)가 읽는다.
- `RetrievalEvaluator.evaluate(items, mode, k, unit, golden_fingerprint=None)`: 호출자가 `GoldenDatasetProvider.fingerprint` 값을 넘기면 보고서의 `golden_fingerprint` 에 남긴다(선택 인자).
- 비동기 규칙 정리: 실시간 경로(`retrieve`, `answer`, `get`)와 이를 동시에 호출하는 평가기(`evaluate`)는 async, 색인·골든 로딩은 sync.
