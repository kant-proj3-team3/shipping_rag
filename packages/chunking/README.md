# chunking

PDF를 읽어 청킹하고, 임베딩해 Qdrant에 색인하고, 인덱스의 신원(`IndexManifest`)을 기록한다. 평가용 골든 데이터셋(`GoldenItem`)도 이 모듈이 정규화해 제공한다. 검색 로직과 LLM 호출은 하지 않는다.

> 현재 상태: **뼈대(목업)**. `create_*`는 `src/chunking/mock/`의 목업을 돌려준다. 실제 구현은 아직 없다.

## 공개 인터페이스

`common.interfaces`의 Protocol 세 개를 제공한다. 진입점은 `common.entrypoints`의 시그니처를 따른다.

| 진입점 | 반환 | 역할 |
|---|---|---|
| `create_embedder()` | `Embedder` | 텍스트 → 벡터. 검색·평가 모듈에 주입된다 |
| `create_indexer(embedder)` | `Indexer` | `build(IndexBuildRequest) -> IndexManifest`, `get_manifest(index_name)` |
| `create_golden_provider()` | `GoldenDatasetProvider` | `load(splits)`, `fingerprint(splits)` |

주입받는 것은 없다. 설정(Qdrant 주소, 모델 캐시, 문서 경로)은 환경변수로 읽는다.

## 지킬 계약 (요약)

- `book_id`는 파일명에서 `.pdf`를 뺀 값, 첫 페이지는 1쪽이다.
- `chunk_id`는 결정적이고, 모든 청크는 `manifest.max_chunk_tokens` 이하다. 색인 payload는 `Chunk` 스키마다.
- `embedder_id`는 모델·접두사·정규화·최대 길이를 구분하고, 한도 초과 입력은 조용히 자르지 않는다(질의는 `InvalidInputError`, 문서는 `IngestError`).
- 빈 본문·중복 `book_id`·읽을 수 없는 PDF는 `manifest.failures`에 기록하고 색인에서 뺀다.
- 정답·채점 기준은 색인하지 않는다. 서비스에는 `question`만 전달된다.

자세한 규칙은 [`CLAUDE.md`](CLAUDE.md)와 루트 [`CONTRACTS.md`](../../CONTRACTS.md)를 본다.

## 목업 (`src/chunking/mock/`)

| 클래스 | 동작 |
|---|---|
| `MockEmbedder` | 해시 기반 결정적 벡터(길이 16). 한도 초과 오류 규칙은 실제와 같다 |
| `MockIndexer` | PDF를 읽지 않고 폴더의 PDF 개수만 센다. `chunk_count`는 고정값(`params.mock=true`로 표시). manifest를 `MOCK_INDEX_DIR`(기본 `./.mock_index`)에 저장해 프로세스가 바뀌어도 유지하며, `build` 전에는 `get_manifest`가 `None`이다. `MOCK_INDEX_READY=1`이면 저장 없이 데모 인덱스를 돌려준다(화면·API 시연용). 같은 이름을 `rebuild=False`로 다시 만들면 `IngestError` |
| `MockGoldenProvider` | 데모 문항 4개. `security`는 기본 제외 |

## 주요 설계 결정

- 아직 없음. 청킹 방식(페이지 경계 처리, 청크 크기), 임베딩 모델(로컬 E5 계열), 인덱스 이름 규칙을 정하면 여기에 기록한다.

## 테스트

```bash
uv run pytest packages/chunking
```
