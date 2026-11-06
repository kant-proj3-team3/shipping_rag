# backend

FastAPI 라우터(`/health`, `/query`, `/session/{id}`), 질문 → 검색 → 프롬프트·모델 호출 → 검증 → 출처 매핑을 하는 QA 서비스, Redis 캐시·세션, Langfuse 기록, 답변 품질 평가를 맡는다. 검색 구현과 청킹은 하지 않는다.

> 현재 상태: **뼈대(목업)**. 라우터는 실제 계약(경로·모델·HTTP 상태)대로 동작하고, QA·세션·평가는 `src/backend/mock/`의 목업이다. LLM, Redis, Langfuse는 아직 연결하지 않았다.

## 공개 인터페이스

| 진입점 | 반환 | 역할 |
|---|---|---|
| `create_qa_service(retriever)` | `QAService` | `answer(QueryRequest, RequestContext) -> QAResult` (async) |
| `create_session_service()` | `SessionService` | `get(session_id, limit) -> SessionInfo \| None` (async) |
| `create_answer_evaluator(embedder)` | `AnswerEvaluator` | `evaluate(records) -> list[AnswerEvaluation]` (async). `embedder`는 `answer_relevancy`를 쓸 때만, 아니면 `None` |
| `create_router(qa_service, session_service, index)` | `fastapi.APIRouter` | HTTP 계약(`contracts/openapi.json`) 구현 |

주입받는 것: `Retriever`, `IndexManifest`. 설정(OpenAI·Langfuse·Redis)은 환경변수로 읽는다.

## 지킬 계약 (요약)

- 검색은 주입된 `Retriever`로만 한다. 검색 모듈을 import하지 않는다.
- 검색 결과가 비면 모델을 호출하지 않고 `abstained`로 답한다.
- 모델 출력은 코드로 검증한다. 문서명·페이지는 모델이 아니라 코드가 `Chunk`에서 채운다. `status=error`는 코드만 부여하고, 예외는 던지지 않고 `status=error`+`error_code`로 돌려준다.
- `meta`의 토큰·비용·`trace_id`는 확인된 값만 채운다(모르면 `None`, 0 금지). `final_context`는 모델에 실제 전달한 문맥과 같다.
- 세션은 `answered`·`needs_clarification`·`abstained`만 기록하고 `error`는 기록하지 않는다. 없거나 만료된 세션은 404 + `ApiError`.
- 캐시 키에는 질문·`retrieval_mode`·`k`·`index_name`+`embedder_id`·프롬프트 버전이 들어간다. 세션 이력을 프롬프트에 쓰면 이력도 키에 넣거나 캐시를 우회한다.
- 검색된 문서의 문장은 지시가 아니라 데이터다(`security` 문항의 공격 문구).

자세한 규칙은 [`CLAUDE.md`](CLAUDE.md)와 루트 [`CONTRACTS.md`](../../CONTRACTS.md)를 본다.

## 목업 (`src/backend/mock/`)

| 클래스 | 동작 |
|---|---|
| `MockQAService` | LLM 없이 1위 청크를 그대로 답으로 쓴다. 질문이 4자 미만이면 `needs_clarification`. 검색 예외를 `error_code`로 변환하고 세션에 기록한다 |
| `MockSessionService` | 프로세스 메모리 저장소(`InMemorySessionStore`)를 `QAService`와 공유한다 (실제는 Redis) |
| `MockAnswerEvaluator` | 채점하지 않는다. 답변은 `unavailable`, 오류 응답도 `unavailable`(평균 제외), 사실 주장이 없는 응답은 `not_applicable` |

라우터(`router.py`)는 목업이 아니라 실제 구현이다. `/query`의 `status=error`는 `ERROR_HTTP_STATUS`로 HTTP 상태를 바꾸고, `final_context`는 응답에 내보내지 않는다.

## 주요 설계 결정

- 아직 없음(목업 단계). 프롬프트 구성, 토큰 예산, 캐시 키 구성, Langfuse 기록 단위를 정하면 여기에 기록한다.
- `create_qa_service`와 `create_session_service`는 서로를 인자로 받지 않으므로, 목업은 모듈 전역 저장소를 공유한다. 실제 구현은 둘 다 `REDIS_URL`을 읽는다.
- 캐시 키의 `index_name`+`embedder_id`는 `retriever.index`에서 읽는다(`create_qa_service`가 `IndexManifest`를 따로 받지 않는다).

## 테스트

```bash
uv run pytest packages/backend
uv run python scripts/export_openapi.py   # contracts/openapi.json 과 같은지 확인 (git diff)
```
