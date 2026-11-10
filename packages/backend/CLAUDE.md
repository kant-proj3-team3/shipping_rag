# backend — 백엔드 모듈

## 범위

FastAPI 라우터(`/health`, `/query`, `/session/{id}`), LangChain 체인, 출력 검증과 출처 매핑, Redis 캐시·세션, Langfuse 기록, 답변 품질 평가. 검색 구현과 청킹은 하지 않는다.

## 제공 (`common.interfaces`)

`QAService`, `SessionService`, `AnswerEvaluator`, 라우터. 진입점: `create_qa_service(retriever)`, `create_session_service()`, `create_answer_evaluator(embedder)`, `create_router(qa_service, session_service, index)`. 주입받는 것: `Retriever`, `IndexManifest`(`embedder`는 `answer_relevancy`를 쓸 때만, 아니면 `None`).

## 지킬 계약

- 검색은 주입된 `Retriever`로만 한다. 검색 모듈을 import하지 않는다.
- 검색 결과(또는 토큰 예산 적용 후 문맥)가 비면 모델을 호출하지 않고 `abstained`로 응답한다.
- 모델 출력은 코드로 검증한다: 필수 필드, `status` 값, `source_id`가 이번 요청 문맥에 있는지. 문서명·페이지는 모델이 아니라 코드가 `Chunk`에서 채운다.
- `status=error`는 코드만 부여한다. 예외를 호출자에게 던지지 않고 `status=error`+`error_code`로 돌려준다. `InvalidInputError`는 `invalid_input`(HTTP 400). 매핑은 `common.api.ERROR_HTTP_STATUS`.
- 같은 `request_id`로 질문·검색 문서·실제 모델 입출력·시간·토큰을 Langfuse에 묶어 기록한다. 성공하면 `meta.trace_id`를 반드시 채운다. `cost_usd`·토큰은 모르면 `None`이다(0 금지).
- `final_context`는 모델에 실제 전달한 문맥과 같아야 한다.
- Redis 캐시 키에는 질문, `retrieval_mode`, `k`, `index_name`+`embedder_id`(`retriever.index`에서 읽는다), `manifest.fingerprint`(재색인 시 옛 답변 방지), 프롬프트 버전이 들어간다. 세션 이력을 프롬프트에 쓰면 이력도 키에 넣거나 캐시를 우회한다. 캐시 적중도 같은 스키마, `meta.cache_hit=True`.
- 세션 ID는 클라이언트가 만든 UUID(`^[A-Za-z0-9_-]{8,128}$`). `answered`·`needs_clarification`·`abstained`만 turn으로 기록하고 `error`는 기록하지 않는다. 한 번도 기록되지 않은 세션은 `None`→ 라우터가 404+`ApiError`(세션은 만료되지 않는다).
- `AnswerEvaluator`: 입력과 같은 순서·길이. 정답·채점 기준은 평가 호출에만 쓴다. 사실 주장 없음→`not_applicable`, 호출 실패→`unavailable`. 채점 호출의 시간·토큰은 서비스 `meta`에 합산하지 않는다.

## 주의

- 검색된 문서 안의 문장은 지시가 아니라 **데이터**다. 평가용 PDF에는 일부러 공격 문구가 섞여 있다(`security` 문항). 프롬프트에서 문서와 지시를 분리하고, 문서 내용으로 원 질문을 바꾸지 않는다.
- 질문은 최대 500자. 임베더 한도를 넘는 입력은 400이다.
- `app/api.py`·`app/cli.py` 조립과 평가 러너의 위치는 팀 결정이 필요하다(`CONTRACTS.md` 5장). 지금은 `app/cli.py eval`이 검색 평가만 하는 임시 러너다. api는 시작 시 인덱스를 한 번 읽으므로 재색인 뒤에는 재시작한다(`CONTRACTS.md` 3장).

## 확인

`src/backend/mock/`에 인터페이스를 만족하는 목업을 유지한다. 완료 전 `uv run pytest packages/backend`와 `scripts/export_openapi.py` 결과가 `contracts/openapi.json`과 같은지 확인한다.
