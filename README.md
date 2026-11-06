# shipping_rag

KANT 프로젝트3 팀3 — 제공된 PDF(해운, 50개)에서 근거를 찾아 답하는 RAG Q&A 서비스. 답변에 문서명·페이지 출처를 붙이고, 근거가 부족하면 되묻거나 보류한다. 검색 방식 세 가지(Naive / 하이브리드 / 하이브리드+리랭킹)를 같은 질문·같은 k로 비교한다.

## 현재 상태

- **뼈대 완료**: 계약(`packages/common`, `contracts/`), 모듈 3개(chunking·retrieval·backend)의 인터페이스와 목업, `app/` 조립, CI·계약 검사.
- **실제 구현은 아직 없다.** 모듈의 `create_*`는 `src/<모듈>/mock/`의 목업을 돌려준다(PDF를 읽지 않고, LLM·Qdrant·Redis·Langfuse를 쓰지 않는다). 목업으로도 API와 CLI 흐름 전체가 돌아간다.
- 다음: 각자 `feat/<모듈>` 브랜치에서 자기 모듈의 안쪽만 구현한다(`CLAUDE.md`의 진행 순서 ②).
- 프론트엔드(`frontend/`)는 아직 시작 전이다.

## 빠른 시작

```bash
uv sync                               # 루트에서 한 번만. 가상환경은 루트에 하나
uv run pytest                         # 전체 테스트 (모듈 + 조립)
uv run python scripts/import_lint.py  # 모듈 경계 검사
uv run python scripts/build_contract_manifest.py --check   # 계약 검사
```

### 목업 API 띄우기 (Docker)

```bash
docker compose up -d --build                          # qdrant + redis + api (.env 는 없어도 된다)
docker compose --profile tools run --rm cli index     # 목업 색인
docker compose restart api                            # api 는 시작 시 한 번만 인덱스를 읽는다
```

`http://localhost:8000/docs`에서 `/health`, `/query`, `/session/{id}`를 확인한다. 색인 전에는 `/health`가 `index_ready:false`다. 색인 없이 화면만 보려면 `.env`에 `MOCK_INDEX_READY=1`을 적고 api를 (재)시작한다.

### 호스트에서 직접 실행

```bash
uv run python -m app.cli index                        # 색인 (같은 이름은 --rebuild 로만 덮어쓴다)
uv run python -m app.cli eval --k 5 --unit page       # 검색 평가: 세 방식 비교 (unit 은 기본값 없음)
uv run uvicorn app.api:create_app --factory           # api (색인을 먼저 한다)
```

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
