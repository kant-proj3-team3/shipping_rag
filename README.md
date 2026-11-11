# shipping_rag

KANT 프로젝트3 팀3 — 제공된 PDF(해운, 50개)에서 근거를 찾아 답하는 RAG Q&A 서비스. 답변에 문서명·페이지 출처를 붙이고, 근거가 부족하면 되묻거나 보류한다. 검색 방식 세 가지(Naive / 하이브리드 / 하이브리드+리랭킹)를 같은 질문·같은 k로 비교한다.

## 현재 상태

- **모듈 3개(chunking·retrieval·backend)의 실제 구현이 모두 들어왔고**, `app/`(api·cli)은 기본으로 실제 구현으로 조립된다. 모듈 단위 테스트와 CI 는 목업으로 돈다(모듈의 기본값은 목업).
- 실제 구성: PDF 구조 청킹·로컬 E5 임베딩 → Qdrant 색인 → 세 검색 방식(Naive / 하이브리드 / 하이브리드+리랭킹) → `gpt-6-luna` 답변 → 출처 검증, PostgreSQL 세션 이력(Redis 캐시), Redis 답변 캐시, Langfuse 기록, 답변 평가(RAGAS Faithfulness + Judge)와 보안 비교.
- 실제 구현에는 `OPENAI_API_KEY`(모델)와 Qdrant·Redis·PostgreSQL(compose)이 필요하다. 키·DB 없이 화면·API 흐름만 보려면 `APP_IMPL=mock`.
- 프론트엔드는 `frontend/`([frontend/README.md](frontend/README.md)).

## 빠른 시작

```bash
uv sync                               # 루트에서 한 번만. 가상환경은 루트에 하나
uv run pytest                         # 전체 테스트 (모듈 + 조립, 목업 기반이라 키·DB 없이 돈다)
uv run python scripts/import_lint.py  # 모듈 경계 검사
uv run python scripts/build_contract_manifest.py --check   # 계약 검사
```

### 실제 구현으로 실행 (Docker)

```bash
cp .env.example .env                                  # OPENAI_API_KEY 와 INDEX_NAME(개인 구분)을 채운다
docker compose up -d qdrant redis postgres            # 인프라
docker compose --profile tools run --rm cli index     # 색인 (처음 한 번, 몇 분. 데이터는 ./data 를 읽기 전용으로 마운트)
docker compose up -d --build                          # api 포함 전체
docker compose restart api                            # 색인(재색인 포함) 뒤에 한다: api 는 시작 시 한 번만 인덱스를 읽는다
```

`http://localhost:8000/docs`에서 `/health`, `/query`, `/session/{id}`를 확인한다. 색인 전에는 `/health`가 `index_ready:false`다.

### 호스트에서 직접 실행

```bash
docker compose up -d qdrant redis postgres            # 인프라는 compose 로
uv run python -m app.cli index                        # 색인 (같은 이름은 --rebuild 로만 덮어쓴다)
uv run uvicorn app.api:create_app --factory           # api (색인을 먼저 한다)
uv run python -m app.cli eval --k 5 --unit page       # 검색 평가: 세 방식 비교 (unit 은 기본값 없음)
uv run python -m app.cli eval-answer --limit 3        # 답변 평가(모델 호출). 보고서는 ./eval_reports
uv run python -m app.cli compare-security             # 보안 문항을 기본·방어 프롬프트로 비교(모델 호출)
```

- 구현 선택: 기본은 실제(`APP_IMPL=real`). `APP_IMPL=mock`이면 목업, 모듈 하나만 바꾸려면 `CHUNKING_IMPL`·`RETRIEVAL_IMPL`·`BACKEND_IMPL`을 직접 준다(모듈별 값이 우선).
- `eval-answer`·`compare-security`는 **답변 캐시를 자동으로 끈다**(지표 왜곡 방지). 같은 설정끼리만 점수를 비교한다. 재현성이 필요하면 `LLM_REASONING_EFFORT=none`, `LLM_TEMPERATURE=0`.
- 보고서에는 `index_fingerprint`·`golden_fingerprint`, 설정(키 제외), 방식별 서비스 지표(분모와 집계 건수 포함)와 평가 점수(채점·해당 없음·평가 불가 건수 포함)가 담긴다.

환경변수는 `.env.example`을 복사해 `.env`로 쓴다(커밋 금지). 목록과 설명은 `.env.example`에 있다. 호스트 실행(`app.cli`, `uvicorn`)은 시작할 때 저장소 루트의 `.env`를 읽고, 셸에 이미 설정된 값은 덮어쓰지 않는다.

## 문서

| 문서 | 내용 |
|---|---|
| [CLAUDE.md](CLAUDE.md) | 사람·에이전트 공통 작업 규칙: 절대 규칙, 브랜치·PR, 모듈 설계 원칙, 명령 |
| [CONTRACTS.md](CONTRACTS.md) | 모듈 계약 요약, 조립, 변경 절차, 팀 합의가 필요한 결정 |
| [contracts/viewer.html](contracts/viewer.html) | 계약을 그림으로 확인 (브라우저로 연다) |
| [contracts/CHANGELOG.md](contracts/CHANGELOG.md) | 계약 버전별 변경 기록 |
| `packages/*/README.md`, `packages/*/CLAUDE.md` | 모듈별 목적·인터페이스·설계 결정, 모듈 작업 규칙 |

코드가 원본이다. 문서와 코드(`packages/common`)가 다르면 코드가 맞다.
