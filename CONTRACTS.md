# 모듈 계약 (CONTRACTS)

각 모듈은 **이 문서와 `packages/common`의 코드만** 보고 병렬 개발한다. 내부 구현은 담당자 자유.
코드가 원본이고 이 문서는 요약이다. 둘이 다르면 코드가 맞다.
사람과 에이전트(Claude Code)가 함께 따르는 작업 규칙(브랜치·PR·모듈 경계)은 루트 `CLAUDE.md`와 각 모듈의 `CLAUDE.md`에 있다.

## 1. 한눈에 보기

| 모듈 | 담당 범위 | 제공하는 것 (`common.interfaces`) | 주입받는 것 |
|---|---|---|---|
| 청킹 | 문서 청킹·인덱싱, 검색 청크 골든 데이터셋 | `Embedder`, `Indexer`, `GoldenDatasetProvider` | 없음 |
| 검색 | RAG 구현, 검색 청크 품질 테스트 | `Retriever`, `RetrievalEvaluator` | `Embedder`, `IndexManifest` |
| 백엔드 | FastAPI, LangChain, Langfuse, Redis | `QAService`, `SessionService`, `AnswerEvaluator`, `/health`·`/query`·`/session` 라우터 | `Retriever`(`retriever.index`로 인덱스 신원 확인), `IndexManifest` |
| 프론트엔드 | React 클라이언트 | 없음 (API 소비자) | `contracts/openapi.json` |

```
app ──조립──▶ chunking · retrieval · backend        (모듈끼리 직접 import 금지)
모든 모듈 ──▶ common (Protocol · 타입 · 오류 · API 상수만)
React ──HTTP──▶ backend router (OpenAPI가 계약)
```

데이터가 모듈 사이를 지나는 길은 딱 세 가지다.

1. **청킹 → 검색**: Qdrant 인덱스. 규격은 `Chunk`(payload), 신원은 `IndexManifest`.
2. **검색 → 백엔드**: `Retriever.retrieve()` → `RetrievalResult`.
3. **백엔드 → 프론트**: HTTP `QueryResponse`.

## 2. 모듈별 계약

### 청킹

- `Indexer.build(IndexBuildRequest) -> IndexManifest`
  - `documents/*.pdf` 전체를 처리한다. 4개로 나뉜 압축을 풀어 **한 폴더(50개 PDF)로 합친 뒤** 넘긴다.
  - 빠진 문서·실패는 `manifest.failures`에 남긴다. 빈 본문, 중복 `book_id`, 읽을 수 없는 PDF도 마찬가지다 (조용히 건너뛰지 않는다).
  - `book_id` = 파일명에서 `.pdf` 제거, 첫 페이지 = 1쪽, 파일명 변경 금지.
  - `chunk_id`는 결정적이다 (같은 문서·내용·청킹 조건이면 같은 값). 청크의 `page_start`~`page_end`는 실제로 걸친 페이지다.
  - 모든 청크는 `manifest.max_chunk_tokens` 이하다. `manifest.fingerprint`는 순서 있는 `(chunk_id, text)` 해시다.
  - 색인 payload는 `Chunk` 스키마(PDF 제목은 `title`). 질문·정답·채점 기준 JSON은 색인하지 않는다.
  - 오래 걸리므로 `progress` 콜백으로 단계(`parse`·`chunk`·`embed`·`upsert`)별 진행을 알린다.
- `Embedder`: 인덱싱과 질의가 같은 `embedder_id`를 쓴다. `embedder_id`는 모델명뿐 아니라 접두사·정규화·최대 입력 길이까지 구분한다.
  - `max_input_tokens`와 `count_tokens`(접두사 포함)를 제공한다. 한도를 넘는 입력은 조용히 자르지 않는다: 질의는 `InvalidInputError`, 문서는 `IngestError`.
- `GoldenDatasetProvider.load(splits) -> list[GoldenItem]`, `fingerprint(splits) -> str`
  - 정답이 든 `development.json`·`additional.json`·`security_tasks.json`을 `GoldenItem`으로 정규화한다. 질문만 든 `*_questions.json`은 같은 id·질문인지 점검하는 용도다.
  - `evidence_groups`: 그룹끼리는 모두 필요(AND), 한 그룹 안의 후보는 하나만 맞으면 된다(OR). 근거는 `(book_id, page, quote)`다.
  - 채점 정보는 `GradingSpec`, 보안 문항은 `SecurityInfo`(공격 유형·공격 문서·`bad_claims`)로 담는다.
  - 서비스에는 `item.question`만 전달한다. 정답·채점·근거는 평가기와 러너만 쓴다.
  - 매핑 참고 구현과 검증은 `scripts/check_dataset_mapping.py`에 있다 (62문항·근거 189곳을 모두 표현하고 실제 PDF와 대조한다).

### 검색

- `Retriever.retrieve(RetrievalRequest, RequestContext) -> RetrievalResult` (async)
  - 방식은 `mode`로만 바꾼다: `naive` / `hybrid` / `hybrid_rerank`.
  - 결과: 길이 ≤ k, `rank`는 1부터 연속, `chunk_id` 중복 없음. **빈 결과는 정상**.
  - 세 방식은 같은 임베딩·저장소·k를 쓴다. `k`는 호출자가 정한다.
  - 인덱스·임베더 불일치는 `IndexNotReadyError`, 그 외 검색 실패는 `RetrievalError`. 질문이 임베더 한도를 넘으면 `InvalidInputError`가 그대로 전파된다.
  - 시작 시 `manifest.max_chunk_tokens`를 자기 리랭커 입력 한도와 대조한다 (안 맞으면 `IndexNotReadyError`). 점수 임계값은 방식마다 척도가 달라 내부 설정이다.
  - `Retriever.index`: 생성 시 주입받은 `IndexManifest` 그대로다. 평가기와 백엔드(캐시 키의 `index_name`+`embedder_id`)가 인덱스 신원을 아는 경로다.
- `RetrievalEvaluator.evaluate(items, mode, k, unit, golden_fingerprint=None) -> RetrievalReport` (async)
  - **근거 그룹 단위**로 계산한다. 그룹이 만족되면 satisfied. Hit@k = 만족한 그룹이 하나라도 있으면 1, Recall@k = 만족한 그룹 수 / 전체 그룹 수.
  - `unit`은 호출자가 명시한다: `document`는 `book_id` 일치, `page`는 청크의 `[page_start, page_end]`가 근거 페이지를 포함해야 일치. 보고서에 `unit`이 남는다.
  - 근거 그룹이 없는 문항(되묻기)은 `not_applicable`, 호출 실패는 `unavailable`. 둘 다 평균에서 제외하고 건수를 보고한다.
  - 검색 결과가 비어도 근거가 있는 문항은 0점으로 센다 (제외 금지). `abstain` 문항도 근거가 있으면 포함한다.
  - `k`가 그룹 수보다 작으면 Recall 만점이 불가능하다 (제공 데이터는 그룹이 최대 7개). 보고서의 `k`와 함께 해석한다.
  - 보고서에 `index_name`·`index_fingerprint`·`golden_fingerprint`를 남겨 다른 인덱스끼리의 비교를 막는다. 앞의 둘은 `retriever.index`에서, `golden_fingerprint`는 호출자가 `GoldenDatasetProvider.fingerprint` 값을 인자로 넘긴다(안 넘기면 `None`).

### 백엔드

- `QAService.answer(QueryRequest, RequestContext) -> QAResult` (async)
  - 검색은 주입된 `Retriever`로만 한다.
  - 모델 출력은 코드로 검증한다: 필수 필드, `status` 값, `source_id`가 이번 요청 문맥에 있는지.
  - 문서명·페이지는 모델이 아니라 코드가 `Chunk`에서 채운다.
  - `status=error`는 코드만 부여한다. 자료 부족은 `abstained`. 검색 결과(또는 토큰 예산 적용 후 문맥)가 비면 모델을 호출하지 않고 `abstained`로 응답한다.
  - `InvalidInputError`(질문이 임베딩 한도 초과)는 `error_code=invalid_input`(HTTP 400)으로 매핑한다.
  - 예외를 호출자에게 던지지 않고 `status=error` + `error_code`로 돌려준다.
  - 같은 `request_id`로 질문·검색 문서·실제 모델 입출력·시간·토큰을 Langfuse에 묶어 기록한다.
  - 기록에 성공하면 `meta.trace_id`를 반드시 채운다 (Langfuse 점수는 `trace_id`에 붙는다). 비용 `meta.cost_usd`는 계산할 수 있을 때만 채우고 모르면 `None`이다.
  - `QAResult.final_context`는 모델에 실제 전달한 문맥과 같아야 한다 (평가 입력).
- **세션 (`/session`)**: `GET /session/{session_id}?limit=20` → `SessionInfo`. 한 번도 기록되지 않은 세션은 404 + `ApiError(session_not_found)`. 세션은 만료되지 않으므로 `SessionInfo.expires_at`은 항상 `null`이다.
  - 세션 ID는 **클라이언트가 UUID로 만들어** `QueryRequest.session_id`로 보낸다 (영문·숫자·`_`·`-` 8~128자). 보내지 않으면 세션 기록 없이 단발 처리한다.
  - `QAService`가 `answered`·`needs_clarification`·`abstained` 응답을 turn으로 기록한다. `error`는 기록하지 않는다.
  - 이력은 영구 저장소(PostgreSQL)가 원본이고 Redis는 조회 캐시다. 기록하는 `question`은 이메일·API 키 모양 문자열을 가린 값이라 대화를 복원할 때 입력 원문과 다를 수 있다.
  - `turns`는 오래된 것 → 최신 순으로 최근 `limit`개, `turn_count`는 전체 개수다.
  - 인증이 없으므로 세션 ID를 아는 사람은 누구나 조회할 수 있다. 추측 불가능한 값을 쓴다.
  - **멀티턴**: `session_id`가 있으면 같은 세션의 이전 질의응답(turn)을 답변에 반영한다. 반영할 turn 수와 방식은 구현이 정한다. 이력을 쓴 요청은 아래 캐시 키에 이력을 반영하거나 캐시를 우회한다 (같은 질문이라도 이력에 따라 답이 달라진다).
- **Redis 캐시**: 계약에 드러나는 것은 `meta.cache_hit`뿐이다. 캐시 적중 조건에는 최소한 질문, `retrieval_mode`, `k`, `index_name`+`embedder_id`(`retriever.index`에서 읽는다), **`manifest.fingerprint`**, 프롬프트 버전이 포함돼야 한다. 같은 이름으로 재색인하면 `fingerprint`가 바뀌고, Redis는 api를 재시작해도 남으므로 `fingerprint`가 없으면 옛 인덱스 기준 답변이 적중한다. 모드가 다른데 적중하면 세 방식 비교가 무의미해진다. 세션 이력의 조회 캐시와 응답 캐시 모두 Redis를 쓰지만 키 공간은 분리한다.
- `AnswerEvaluator.evaluate(records) -> list[AnswerEvaluation]`: 입력과 같은 순서·길이. 사실 주장 없음 → `not_applicable`, 평가 실패 → `unavailable`. 채점 호출의 시간·토큰은 서비스 `meta`에 합산하지 않는다.
  - `faithfulness`는 필수, `answer_relevancy`·`context_recall`·`context_precision`은 `ragas_extra`에 키로 담는다. `answer_relevancy`는 질문 임베딩이 필요해 생성 시 `Embedder`를 주입받는다 (안 쓰면 `None`).
  - 정답·채점 기준(`GradingSpec`)은 평가 호출에만 전달한다. 보안 문항은 `security.bad_claims`가 응답에 나타나면 감점한다.
- **HTTP**: `ERROR_HTTP_STATUS`(`common/api.py`)가 `error_code`→HTTP 상태 매핑이다. 정상 처리된 세 상태는 모두 200, 스키마 검증 실패는 422, 처리할 수 없는 입력(질문 길이 한도 초과 등)은 400. 질문은 최대 500자다.

| error_code | HTTP |
|---|---|
| `invalid_input` | 400 |
| `index_not_ready` | 503 |
| `retrieval_failed` / `model_failed` / `output_invalid` | 502 |
| `model_timeout` | 504 |
| `internal` | 500 |

### 프론트엔드

- 소비하는 계약: `contracts/openapi.json` (`/health`, `/query`). TS 타입은 이 파일에서 생성한다 (손으로 따로 쓰지 않는다).
- `/health`의 `supported_modes`로 검색 방식 선택 UI를 만들 수 있다.
- 세션: 첫 질문 전에 UUID를 만들어 `session_id`로 보낸다. 새로고침 후에는 `GET /session/{id}`로 대화 이력을 복원하고, 404면 새 세션을 시작한다.
- 화면이 구분해서 보여야 하는 것:

| status | 화면 책임 |
|---|---|
| `answered` | 답변 + 출처(문서명·페이지) |
| `needs_clarification` | 되묻는 문장 + 보완 질문 입력 (대화 메모리 없이 완성된 질문을 새로 보내도 된다) |
| `abstained` | 보류 이유 + 필요한 자료 설명. 오류처럼 보이지 않게 구분 |
| `error` | 사용자용 오류 문구. `error_code`는 로그용 |

- 병렬 개발용 목업 데이터: `contracts/examples/*.json` (4개 상태 + health + session). `scripts/check_examples.py`가 계약 통과를 보장한다.
- `source_id`(S1…)는 요청 안에서만 유효한 값이다. 화면에는 `citations`의 문서명·페이지를 보여주고 `source_id`를 노출하지 않는다.

## 3. 조립 (app/)

각 모듈은 최상위에 아래 함수를 노출한다 (`common/entrypoints.py`에 시그니처). 설정은 환경변수로 읽고, 인자는 다른 모듈에서 오는 협력 객체뿐이다. `.env` 파일은 `app/`만 읽는다(호스트 실행 시 시작할 때 적용하고, 이미 설정된 환경변수는 덮어쓰지 않는다). 모듈은 환경변수만 본다.

```
chunking.create_embedder()                        -> Embedder
chunking.create_indexer(embedder)                 -> Indexer
chunking.create_golden_provider()                 -> GoldenDatasetProvider
retrieval.create_retriever(embedder, index)       -> Retriever
retrieval.create_retrieval_evaluator(retriever)   -> RetrievalEvaluator
backend.create_qa_service(retriever)              -> QAService
backend.create_session_service()                  -> SessionService
backend.create_answer_evaluator(embedder)          -> AnswerEvaluator   # embedder: answer_relevancy를 쓸 때만, 아니면 None
backend.create_router(qa_service, session_service, index) -> fastapi.APIRouter
```

### 인덱스 반영 (api)

api는 시작 시 `Indexer.get_manifest(index_name)`를 한 번 읽어 검색기·QA 서비스·라우터를 만든다. 인덱스가 없으면 죽지 않고 `/health`가 `index_ready=false`로 알린다(`/query`는 아직 없다). **색인·재색인 뒤에는 api를 재시작한다.** 실행 중 자동 반영(주기 확인 후 재조립)은 아직 없고, 필요해지면 `app/`에서 계약 변경 없이 추가할 수 있다.

## 4. 변경 절차

- `packages/common/**`와 `contracts/**` 변경은 전부 **계약 변경 PR**이다. 영향받는 모듈 담당자의 승인을 받는다.
- 계약을 바꾸면 순서대로: ① 타입·인터페이스·`api.py` 수정 ② `packages/common/src/common/version.py`의 `CONTRACT_VERSION`을 올린다(0.x에서는 삭제·이름 변경에 minor, 호환되는 추가에 patch) ③ `contracts/CHANGELOG.md`에 `## [x.y.z]` 항목을 쓴다 ④ `uv run python scripts/build_contract_manifest.py` 실행(예시 JSON 검사, `openapi.json`·`viewer.html` 재생성, `manifest.json` 작성을 한 번에 한다. 개별 실행: `export_openapi.py`, `build_contract_viewer.py`, `check_examples.py`) ⑤ 각 모듈의 목업과 `[tool.rag-contract] version` 갱신 ⑥ 병합 즉시 각자 `dev`를 자기 브랜치에 반영. CI의 `contract-test`가 `--check`로 같은 것을 확인한다.
- 호환 규칙: 필드 추가는 선택(기본값 있음)으로만 한다. 삭제·이름 변경·의미 변경은 모든 소비자를 같은 PR에서 고친다.

CODEOWNERS는 `.github/CODEOWNERS`가 원본이다. 한 줄에 여러 명을 적으면 그중 한 명의 승인으로 충분하므로, 영향받는 담당자는 PR 리뷰어로 직접 지정한다. 작성자는 자기 PR을 승인할 수 없으니 경로마다 소유자를 2명 이상 둔다.

## 5. 팀 합의가 필요한 결정

1. 실시간 경로(`retrieve`, `answer`)와 그것을 동시에 호출하는 평가기(`evaluate`)를 async, 색인·골든 로딩 같은 배치 경로를 sync로 둔 것에 동의하는가. (평가기는 문항×방식을 `gather`로 병렬 호출하고 CLI가 `asyncio.run`으로 실행한다.)
2. 모델 호출 실패의 HTTP 상태(502/504)와 본문 구조(`status=error`)를 위 표대로 쓸 것인가.
3. 평가 러너(질문 전체 × 세 방식 실행, 비교표 생성)는 `app/`의 스크립트로 둘 것인가. 이 계약에는 러너를 넣지 않았다. (현황: `app/cli.py eval`이 검색 평가만 하는 임시 러너로 있고, 답변 평가(`AnswerEvaluator`) 러너는 아직 없다.)
4. 검색 평가 단위(`document` / `page`)를 무엇으로 보고할 것인가. 제공 데이터는 문서당 60~95페이지, 정답 근거는 전체 3,750페이지 중 126페이지(3.4%)라 문서 단위는 쉽게 포화된다 (간단한 BM25 기준선에서 Hit@5가 문서 0.98, 페이지 0.93, Recall@5가 0.76 대 0.62). 발제문의 정의를 확인하고 정한다.
5. 프론트엔드가 `packages/` 밖(`frontend/`)에 놓이는 것을 진행 방식 문서의 레포 구조에 반영할 것인가.
6. 세션 ID를 클라이언트가 만드는 방식(서버 발급 아님), `error` 응답을 turn으로 기록하지 않는 규칙, 세션 이력의 영구 저장(만료 없음, `expires_at`은 항상 `null`)과 질문의 이메일·키 마스킹 저장에 동의하는가. 같은 세션의 이전 turn을 답변에 반영하는 멀티턴에 동의하는가.
7. 보류(`abstained`)·되묻기 응답에 출처를 붙일 수 있게 둔 것에 동의하는가. 교안(`validate_answer`)은 보류 응답의 출처를 빈 배열로 강제하지만, 제공 데이터의 `abstain` 문항은 근거 그룹을 가지므로(설명에 쓰인 문서) 계약은 허용한다.
8. RAGAS 선택 지표(`answer_relevancy`·`context_recall`·`context_precision`)를 쓸 것인가. 쓰면 `AnswerEvaluator`에 `Embedder`가 주입된다.
9. `QueryRequest.question` 최대 500자(제공 데이터의 가장 긴 질문은 170자)와 `invalid_input`→400 매핑에 동의하는가.
