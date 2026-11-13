# shipping_rag

KANT 프로젝트3 팀3 — 제공된 PDF(해운, 50개·3,750페이지)에서 근거를 찾아 답하는 RAG Q&A 서비스.
답변에 문서명·페이지 출처를 붙이고, 근거가 부족하면 되묻거나 보류한다.
검색 방식 세 가지(Naive / 하이브리드 / 하이브리드+리랭킹)를 같은 질문·같은 k로 비교한다.

## 구조 한눈에

```text
PDF ─▶ chunking ─▶ Qdrant 인덱스 ─▶ retrieval ─▶ backend ─▶ HTTP(/query) ─▶ frontend
       (청킹·임베딩·색인)           (검색 3종·검색 평가)  (답변 생성·검증·세션·답변 평가)   (React)
```

| 구성 | 위치 | 역할 |
|---|---|---|
| 조립 | `app/` | `api.py`(FastAPI), `cli.py`(index / eval / eval-answer / compare-security), `wiring.py`. 모듈을 아는 곳은 여기뿐이다 |
| 계약 | `packages/common/` | 인터페이스·타입·오류·API 상수만 둔다(구현 없음). 모듈은 `common`만 import한다 |
| 청킹 | `packages/chunking/` | PDF 구조 청킹, 로컬 E5 임베딩, Qdrant 색인, 골든 데이터셋 |
| 검색 | `packages/retrieval/` | Naive(Dense) / 하이브리드(+BM25) / +리랭킹, 검색 품질 평가(Hit@k·Recall@k) |
| 백엔드 | `packages/backend/` | `gpt-6-luna` 답변 생성, 출처 검증, Redis 캐시, PostgreSQL 세션, Langfuse, 답변 평가(RAGAS + Judge) |
| 프론트 | `frontend/` | React 클라이언트. `contracts/openapi.json`을 소비한다 |
| 계약 산출물 | `contracts/` | `openapi.json`, `manifest.json`, `CHANGELOG.md`, `viewer.html` |
| 인프라 | 루트 | `docker-compose.yml`(qdrant · redis · postgres · api · cli), `docker-compose.gpu.yml` |

모듈 3개는 서로 import하지 않고 `common`만 본다(`scripts/import_lint.py`가 검사). 데이터가 모듈 사이를 지나는 길은 셋뿐이다: 청킹→검색은 Qdrant 인덱스, 검색→백엔드는 `Retriever.retrieve()`, 백엔드→프론트는 HTTP `QueryResponse`.

## 준비물

| 도구 | 용도 |
|---|---|
| [Docker](https://docs.docker.com/get-docker/) (Compose 포함) | qdrant · redis · postgres · api 실행. **데몬이 켜져 있어야 한다** |
| [uv](https://docs.astral.sh/uv/) + Python 3.12 | 테스트·CLI·호스트 실행 (가상환경은 루트에 하나) |
| [Node.js](https://nodejs.org/) | 프론트 타입 생성·개발 서버 (Docker로만 띄우면 불필요) |
| `OPENAI_API_KEY` | 실제 구현의 답변 생성·평가. 목업(`APP_IMPL=mock`)은 필요 없다 |
| (선택) NVIDIA GPU | 임베딩·리랭킹 속도. 아래 [GPU로 실행](#gpu로-실행) 참고 |

### 데이터 배치

원본 PDF와 평가 파일은 저장소에 없다(`data/`는 git 제외). 4개로 나뉜 압축을 풀어 아래처럼 둔다. 원본은 수정하지 않는다.

```text
data/
├─ documents/     # PDF 50개 (IS01 ~ IS50) 를 한 폴더로 합친다
└─ evaluation/    # development.json, additional.json, security_tasks.json (정답)
                  # development_questions.json, additional_questions.json, security_questions.json (질문만)
```

경로는 `.env`의 `DOCUMENTS_DIR`·`EVALUATION_DIR`로 바꿀 수 있다.

## 빠른 시작

### 1. 키·DB 없이 코드만 확인 (목업)

```bash
uv sync                                                     # 루트에서 한 번만
uv run pytest                                               # 전체 테스트 (모듈 + 조립, 목업 기반)
uv run python scripts/import_lint.py                        # 모듈 경계 검사
uv run python scripts/build_contract_manifest.py --check    # 계약 검사
```

### 2. 실제 구현으로 실행 (Docker)

```bash
cp .env.example .env                                  # OPENAI_API_KEY 와 INDEX_NAME(개인 구분)을 채운다
docker compose up -d qdrant redis postgres            # 인프라
docker compose --profile tools run --rm cli index     # 색인 (처음 한 번, 몇 분. ./data 를 읽기 전용으로 마운트)
docker compose up -d --build                          # api 포함 전체
docker compose restart api                            # 색인(재색인 포함) 뒤에 한다: api 는 시작 시 한 번만 인덱스를 읽는다
```

api는 첫 시작에 모델을 불러오느라 `/health` 응답까지 1분 안팎 걸릴 수 있다. 준비되면 아래가 `index_ready: true`를 돌려준다.

```bash
curl http://localhost:8000/health
```

`http://localhost:8000/docs`에서 `/health`, `/query`, `/session/{id}`를 시험해 볼 수 있다.

### 3. 프론트 화면

```bash
docker compose -f frontend/docker-compose.yml up -d --build
```

`http://localhost:3000`을 열어 왼쪽 아래가 "서버 정상"이면 준비 완료다. 개발 서버·화면 로그·API 타입 생성은 [frontend/README.md](frontend/README.md).

### GPU로 실행

기본 compose는 **CPU**로 돈다(임베더·리랭커가 느리다). NVIDIA GPU가 있으면 override 파일을 겹쳐 올린다. Windows는 Docker Desktop의 WSL2 백엔드가 필요하다.

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile tools run --rm cli index
```

적용 여부는 컨테이너 안에서 확인한다.

```bash
docker exec rag-qa-api-1 python -c "import torch; print(torch.cuda.is_available())"   # True 여야 한다
```

### 호스트에서 직접 실행

```bash
docker compose up -d qdrant redis postgres            # 인프라는 compose 로
uv run python -m app.cli index                        # 색인 (같은 이름은 --rebuild 로만 덮어쓴다)
uv run uvicorn app.api:create_app --factory           # api (색인을 먼저 한다)
```

`.env`의 주소는 `localhost`를 쓴다. 호스트 실행은 시작할 때 저장소 루트의 `.env`를 읽고, 셸에 이미 설정된 값은 덮어쓰지 않는다. 브라우저의 프론트 개발 서버(`npm run dev`)에서 api를 직접 부르려면 `CORS_ALLOW_ORIGINS=http://localhost:5173`을 준다.

## API 사용 예

`POST /query`는 질문과 검색 방식(`naive` / `hybrid` / `hybrid_rerank`)을 받는다.

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  --data-binary @contracts/examples/query_request.json
```

응답의 `status`는 `answered` / `needs_clarification` / `abstained` / `error` 중 하나이고, `citations`에 문서명·페이지가 들어 있다. `meta`에는 지연 시간·토큰·`cache_hit`·`trace_id`가 있다. 예시는 [contracts/examples/](contracts/examples/)에 있다.

> Windows Git Bash에서는 한글 JSON을 `-d`로 직접 넘기면 400(`error parsing the body`)이 날 수 있다. 위처럼 파일로 보내거나 `--data-binary @파일`을 쓴다.

## 평가

```bash
uv run python -m app.cli eval --k 5 --unit page                          # 검색 평가: 세 방식 비교 (unit 은 기본값 없음)
uv run python -m app.cli eval-answer --limit 3                           # 답변 평가(모델 호출). 보고서는 ./eval_reports
uv run python -m app.cli compare-security                                # 보안 문항을 기본·방어 프롬프트로 비교(모델 호출)
```

- **검색 평가**: 세 방식을 같은 임베딩·저장소·k·질문으로 비교한다. 근거 그룹은 그룹끼리 AND, 그룹 안 후보는 OR다. 단위(`document`/`page`)를 명시해야 한다.
- **답변 평가**: RAGAS Faithfulness와 LLM Judge(decision · facts · conditions · evidence)로 채점한다. 기본 검색 방식은 하이브리드+리랭킹(`--mode`로 바꾼다).
  - **캐시를 자동으로 끈다**(지표 왜곡 방지). 같은 설정(`k`·프롬프트 버전·인덱스)끼리만 점수를 비교한다.
  - 재현성이 필요하면 `LLM_REASONING_EFFORT=none`, `LLM_TEMPERATURE=0`.
  - 실행은 느리다(채점 호출의 모델 API 대기). 병렬로 여러 번 돌리지 않는다.
- **보고서**: `index_fingerprint`·`golden_fingerprint`, 설정(키 제외), 방식별 서비스 지표(분모와 집계 건수 포함), 점수(채점·해당 없음·평가 불가 건수 포함)를 담는다. `eval_reports/`는 git에 올리지 않는다.

정리된 결과 문서:

| 문서 | 내용 |
|---|---|
| [retrieval 품질 보고서](packages/retrieval/report/retrieval_quality_report.md) | 세 검색 방식의 Hit@k·Recall@k 비교 |
| [프롬프트 개선 기록](packages/backend/PROMPT_LOG.md) · [보고서](packages/backend/report/prompt-engineering.md) | 프롬프트 v2 → v3 → v4 시도와 채택 결정 |
| [보안 점검 결과](packages/backend/report/security-check-v3.md) | 문서 속 공격 문구 방어 점검 |

## 구현 선택과 환경변수

기본은 실제 구현(`APP_IMPL=real`)이다. `APP_IMPL=mock`이면 세 모듈 모두 목업이고, 모듈 하나만 바꾸려면 `CHUNKING_IMPL`·`RETRIEVAL_IMPL`·`BACKEND_IMPL`을 직접 준다(모듈별 값이 우선). 모듈의 기본값은 목업이라 모듈 단위 테스트와 CI는 키·DB 없이 돈다.

자주 쓰는 값만 적는다. 전체 목록과 설명은 [.env.example](.env.example).

| 변수 | 의미 |
|---|---|
| `OPENAI_API_KEY` | 모델 호출 키. 없으면 `/query`가 `model_failed` |
| `INDEX_NAME` | Qdrant 컬렉션 이름. **개인 구분을 넣어** 서로 덮어쓰지 않게 한다 (자리표시자를 두면 오류) |
| `QDRANT_URL` · `REDIS_URL` · `DATABASE_URL` | 외부 서비스 주소. compose 안의 `api`·`cli`는 서비스 이름으로 덮어쓴다 |
| `LLM_MODEL` · `ANSWER_K` | 답변 모델(기본 `gpt-6-luna`), 답변에 넘기는 검색 결과 수(기본 10) |
| `CACHE_ENABLED` | 답변 캐시(Redis). 평가 때는 꺼야 한다 |
| `LANGFUSE_PUBLIC_KEY` · `LANGFUSE_SECRET_KEY` · `LANGFUSE_HOST` | 요청 추적 기록 |

`.env`는 커밋하지 않는다. 시크릿은 `.env.example`에 자리만 둔다.

## 문제 해결

| 증상 | 확인 |
|---|---|
| `failed to connect to the docker API` | Docker Desktop(데몬)이 꺼져 있다. 켠 뒤 다시 실행한다 |
| `/health`가 `index_ready: false` | 색인을 하지 않았거나, 색인 뒤 api를 재시작하지 않았다. `INDEX_NAME`이 색인 때와 같은지도 본다 |
| 같은 `index_name`을 색인하면 "이미 있는 인덱스" 오류 | 덮어쓰려면 `--rebuild`. 단 `fingerprint`가 바뀌므로 api를 재시작한다 |
| 응답이 너무 느리다 | GPU 없이 CPU로 떠 있을 수 있다. [GPU로 실행](#gpu로-실행)의 확인 명령을 본다 |
| 한글이 깨지거나 인코딩 오류 (Windows 콘솔) | `PYTHONUTF8=1`을 설정한다 |
| 3000 포트 충돌 (프론트) | `WEB_PORT=3001`처럼 바꿔 띄운다 |

## 협업 규칙

- `main`·`dev`에 직접 push하지 않는다. `feat/<모듈>`·`fix/<모듈>` → `dev` → `main` 순서로 PR을 올린다.
- PR 제목은 Conventional Commits 형식(`feat(retrieval): 하이브리드 검색 추가`)이고, 본문 템플릿의 항목을 채운다.
- `packages/common/**`, `contracts/**` 변경은 계약 변경 PR이다. `CONTRACT_VERSION`을 올리고 `contracts/CHANGELOG.md`에 적은 뒤 `scripts/build_contract_manifest.py`를 실행한다.
- PR 전에 `uv run pytest` 전체, `import_lint.py`, `build_contract_manifest.py --check`를 돌린다.

## 문서

| 문서 | 내용 |
|---|---|
| [CLAUDE.md](CLAUDE.md) | 사람·에이전트 공통 작업 규칙: 절대 규칙, 브랜치·PR, 모듈 설계 원칙, 명령 |
| [CONTRACTS.md](CONTRACTS.md) | 모듈 계약 요약, 조립, 변경 절차, 팀 합의가 필요한 결정 |
| [contracts/viewer.html](contracts/viewer.html) | 계약을 그림으로 확인 (브라우저로 연다) |
| [contracts/CHANGELOG.md](contracts/CHANGELOG.md) | 계약 버전별 변경 기록 |
| `packages/*/README.md`, `packages/*/CLAUDE.md` | 모듈별 목적·인터페이스·설계 결정, 모듈 작업 규칙 |
| [frontend/README.md](frontend/README.md) | 프론트 실행·화면 로그·API 타입 생성 |

코드가 원본이다. 문서와 코드(`packages/common`)가 다르면 코드가 맞다.
