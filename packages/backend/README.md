# backend

FastAPI 라우터(`/health`, `/query`, `/session/{id}`), 질문 → 검색 → 프롬프트·모델 호출 → 검증 → 출처 매핑을 하는 QA 서비스, Redis 캐시·세션, Langfuse 기록, 답변 품질 평가를 맡는다. 검색 구현과 청킹은 하지 않는다.

> 현재 상태: **구현 진행 중**. 라우터는 실제 계약(경로·모델·HTTP 상태)대로 동작한다. 실제 QA 서비스(`qa.py`: 검색 → 문맥 → 모델 → 검증), Langfuse 기록(`tracing.py`), Redis 세션(`session.py`)은 구현됐지만, `create_qa_service`와 `create_session_service`는 아직 `src/backend/mock/`의 목업을 돌려준다(전환은 I 단계). 평가는 목업이고 캐시는 아직 없다. 진행 현황은 [`IMPLEMENTATION.md`](IMPLEMENTATION.md).

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

- 모델 호출(`chain.py`): 모델은 `json_schema`(strict) 구조화 출력으로 `ModelOutput` 스키마를 강제받는다(Chat Completions 고정). 재시도는 별도 요청이 아니라 같은 요청의 일부다. 호출 실패와 읽을 수 없는 출력(`parsed=None`)을 같은 시도 예산으로 다시 시도하고, 토큰은 응답을 받은 시도만 합산한다(하나라도 사용량이 없으면 `None`). 끝내 응답이 없으면 `ModelTimeoutError`/`ModelCallError`, 응답은 있으나 못 읽으면 `ChainResult.output=None`으로 돌려주고 `output_invalid` 판단은 검증 단계가 한다. 스키마가 입력 토큰을 약 20% 늘린다.
- 출력 검증(`validate.py`): 출처는 모델이 쓴 문서명·페이지가 아니라 이번 요청의 문맥(`Chunk`)에서 코드가 채운다. 범위 밖 `source_id`는 항상 거부하고, `abstained`의 출처는 범위 안이면 허용한다. 여러 페이지에 걸친 청크는 페이지마다 `Citation`을 만든다. 검증이 끝내 실패하면 예외 없이 실패 이유를 돌려주고 `output_invalid`로 바꾸는 일은 QA 서비스가 한다.
- Langfuse 기록(`tracing.py`): 요청 하나가 trace 하나다. 트리는 `qa-query`(질문 → status·answer·citations, 메타에 request_id·토큰·시간·오류 코드) 아래에 `retrieve`(순위·점수·chunk_id 전부), `build-context`(예산 적용 전후, S번호↔chunk_id, 제외된 chunk_id), `generate-answer`(LangChain 콜백이 만든 모델 호출 단계)가 붙는다. 검색에는 있는데 `dropped_chunk_ids`에 있으면 문맥 축소로 빠진 것이고, 처음부터 없으면 검색 단계 문제다.
  - `trace_id`는 `request_id`를 씨앗으로 만들어(같은 요청은 같은 trace) **로컬에서 만든 식별자**다. 전송은 SDK가 백그라운드로 하므로 `meta.trace_id`는 "기록을 시작했다"는 뜻이고, 서버 도착은 아래 확인 방법으로 본다. 기록을 시작하지 못하면 `None`이다.
  - 장애 격리: 트레이서는 항상 예외를 모두 잡는 래퍼로 감싸진다. Langfuse가 꺼져 있거나 SDK가 예외를 내도 응답은 그대로 나가고 `trace_id=None`이다. 요청 경로에서 `flush()`를 부르지 않는다.
  - 마스킹: 전송 직전에 모든 문자열 속성에서 이메일과 API 키(환경에 설정된 키 값 자체 포함)를 가린다. 정규식이라 이름·주소 같은 다른 개인정보는 막지 못한다. 질문 원문은 이 규칙만 적용해 남긴다.
  - `cost_usd`는 채우지 않는다(`None`). 서버가 계산하는 비용은 응답 시점에 알 수 없고, 임의 단가를 쓰지 않는다.
- Redis 세션(`session.py`): 세션 하나가 키 두 개다. `rag:session:{id}:meta`(hash: 생성·마지막 활동 시각, 전체 턴 수)와 `rag:session:{id}:turns`(list: `SessionTurn` JSON, 오래된 것 → 최신 순). 기록은 한 트랜잭션으로 두 키를 함께 갱신하고 TTL을 다시 건다(마지막 활동 기준 만료, 조회는 TTL을 늘리지 않는다). 모든 키에 TTL이 있다(compose의 Redis는 `volatile-lru`라 TTL 없는 키는 지워지지 않는다).
  - `turn_count`는 목록 길이가 아니라 카운터라서, 보관 상한(`SESSION_MAX_TURNS`)을 넘겨 오래된 턴이 잘려도 전체 개수는 유지된다.
  - `session_id`는 키에 들어가므로 `SESSION_ID_PATTERN`에 맞는 값만 쓴다. 맞지 않으면 조회는 `None`, 기록은 `ValueError`(QAService가 기록 실패로 처리).
  - **장애 처리**: Redis가 꺼져 있어도 객체 생성과 앱 기동은 실패하지 않고(연결은 첫 명령 때), 소켓 timeout(`REDIS_TIMEOUT_S`)이 있어 멈춘 Redis에 오래 붙잡히지 않는다. 기록이 실패하면 `/query`는 세션 기록만 건너뛰고 응답한다. 조회(`GET /session`)가 실패하면 `None`(404)으로 바꾸지 않고 예외를 낸다(클라이언트가 세션이 사라졌다고 오해해 새 세션을 시작하지 않게). 이때 HTTP 응답은 FastAPI 기본 500이다(`ApiError` 형식이 아니다. 계약에 이 경우의 오류 코드가 없다).
  - 클라이언트가 동기라서 QAService와 `RedisSessionService`가 `asyncio.to_thread`로 이벤트 루프 밖에서 부른다. Redis가 멈춰도 다른 요청은 막히지 않지만, 세션 기록은 응답 전에 하므로 그 요청은 timeout까지 늦어진다.
  - 알려진 한계: 같은 세션에 여러 worker가 기록해도 Redis가 한 줄로 처리하므로 안전하지만, 요청이 거의 동시에 오면 턴 순서는 기록이 도착한 순서이고 `asked_at`과 다를 수 있다.
- 아직 정하지 않은 것: 캐시 키 구성.
- `create_qa_service`와 `create_session_service`는 서로를 인자로 받지 않으므로, 목업은 모듈 전역 저장소를 공유한다. 실제 구현은 둘 다 `REDIS_URL`을 읽는다.
- 캐시 키의 `index_name`+`embedder_id`는 `retriever.index`에서 읽는다(`create_qa_service`가 `IndexManifest`를 따로 받지 않는다).

## 설정 (환경변수)

| 이름 | 기본값 | 설명 |
|---|---|---|
| `OPENAI_API_KEY` | (없음) | `ChatOpenAI`가 읽는다. 커밋하지 않는다 |
| `LLM_MODEL` | `gpt-6-luna` | 생성 모델 |
| `LLM_TIMEOUT_S` | `60` | 모델 호출 1회 timeout(초) |
| `LLM_MAX_RETRIES` | `2` | 첫 호출 뒤 추가 시도 횟수 |
| `LLM_REASONING_EFFORT` | `medium` | 추론 강도(none, low, medium, high, xhigh, max 중 하나). 잘못된 값이면 기본값 |
| `LLM_TEMPERATURE` | (비움) | `none`일 때만 적용되는 temperature(0~2). 추론이 켜져 있으면 모델이 거부하므로 보내지 않고 경고를 남긴다. 재현성이 필요하면 `LLM_REASONING_EFFORT=none`과 `0`으로 고정 |
| `LLM_MAX_CALLS` | `3` | 한 요청의 모델 호출 상한(체인 재시도와 검증 재생성의 합). 체인 시도 횟수는 `min(1+MAX_RETRIES, MAX_CALLS)` |
| `OUTPUT_MAX_REGENERATIONS` | `1` | 출력 검증에 실패했을 때 다시 생성하는 최대 횟수. 0이면 재생성하지 않는다 |
| `REDIS_URL` | `redis://localhost:6379/0` | 세션 Redis 주소. compose 안에서는 `redis://redis:6379/0`로 덮어쓴다 |
| `REDIS_TIMEOUT_S` | `2` | Redis 연결·명령 timeout(초). 멈춘 Redis가 요청을 오래 붙잡지 않게 한다 |
| `SESSION_TTL_SECONDS` | `86400` | 세션 만료(마지막 기록 기준, 초) |
| `SESSION_MAX_TURNS` | `200` | 세션당 보관하는 최근 턴 수(넘으면 오래된 턴부터 지운다. `turn_count`는 유지) |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | (없음) | 둘 다 있어야 기록한다. 없으면 기록 없이 동작한다. 커밋하지 않는다 |
| `LANGFUSE_BASE_URL` 또는 `LANGFUSE_HOST` | `https://cloud.langfuse.com` | 프로젝트 지역 주소(EU `cloud`, US `us.cloud`, JP `jp.cloud`). SDK가 둘 다 읽는다(`BASE_URL` 우선) |
| `LANGFUSE_TRACING_ENABLED` | `true` | `false`면 키가 있어도 기록하지 않는다 |

기본값은 임시이며 팀이 정하면 환경변수로 바꾼다.

## Langfuse 기록 확인

1. `.env`에 위 Langfuse 변수를 채우고(앱은 시작할 때 `.env`를 읽는다) 질문을 보낸다. 응답의 `meta.trace_id`를 적어 둔다.
2. Langfuse 화면 → Tracing에서 그 trace를 연다. 왼쪽 Tree에 `qa-query` 아래 `retrieve` → `build-context` → `generate-answer`(→ `ChatOpenAI` GENERATION)가 보이고, `qa-query` 메타데이터에 `request_id`가 있다. 안 보이면 프로젝트·지역·기간 필터와 반영 지연(수 초)을 확인한다.
   - GENERATION의 입력·출력·토큰: 입력은 비캐시분과 캐시 생성분으로, 출력은 일반분과 추론분으로 나뉘어 표시된다. 합치면 응답 `meta`의 입출력 토큰과 같다.
   - 구조화 출력 때문에 LangChain 내부 노드(`RunnableSequence`, `RunnableParallel`, `_check_refusal` 등)도 함께 기록되어 observation이 10여 개로 보인다. 핵심 단계는 `qa-query`, `retrieve`, `build-context`, `generate-answer`, `ChatOpenAI`다.
3. 코드로 다시 조회할 때: `Langfuse().api.observations.get_many(trace_id=..., fields="core,basic,io", from_start_time=..., to_start_time=...)`. `trace_id`는 `Langfuse.create_trace_id(seed=request_id)`로도 구할 수 있다.
4. 프로세스를 바로 끝내는 스크립트에서는 종료 전에 `create_tracer().flush()`를 한 번 부른다(남은 기록 전송).

## 테스트

```bash
uv run pytest packages/backend
uv run python scripts/export_openapi.py   # contracts/openapi.json 과 같은지 확인 (git diff)
```

세션 테스트(`tests/test_session.py`)는 메모리 Redis(`fakeredis`, 루트 dev 의존성)로 돌아서 Redis 서버가 필요 없다. 실제 Redis에서 확인하려면 `docker compose up -d redis`로 띄우고 `REDIS_URL`을 가리킨 뒤 `create_session_store()`로 기록·조회해 본다.
