# chunking

PDF를 읽어 청킹하고, 임베딩해 Qdrant에 색인하고, 인덱스의 신원(`IndexManifest`)을 기록한다. 평가용 골든 데이터셋(`GoldenItem`)도 이 모듈이 정규화해 제공한다. 검색 로직과 LLM 호출은 하지 않는다.

> 현재 상태: **청킹 구현 중**. PDF 추출(`pdf_parser.py`)과 청킹(`chunker.py`)을 구현했다. 임베딩·색인·골든셋은 다음 PR에서 추가하며, 그때까지 `create_*`는 `src/chunking/mock/`의 목업을 돌려준다.

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

## 파일 구성

| 파일 | 역할 |
|---|---|
| `pdf_parser.py` | pdfplumber로 PDF 페이지를 구역(제목·설명·표·메모·정리)으로 나눈다 |
| `chunker.py` | 페이지 구역 → `Chunk` |
| `mock/` | 목업 (인터페이스를 그대로 만족하도록 유지한다) |

## 주요 설계 결정

### 1. 추출은 pdfplumber, 구역은 글자 크기로 나눈다

- **결정**: 표는 pdfplumber의 표 인식으로 행·칸 단위로 읽고, 나머지는 글자 크기로 구분한다. 16.0 소제목, 10.2 본문(표 위면 설명, 아래면 정리), 8.6·9.2 메모, 8.5 문서 제목, 7.4 장 제목. 머리말 첫 줄(8.0)과 꼬리말 `n / N`(7.5)은 버린다.
- **이유**: pypdf는 칸 구분과 글자 크기를 버려서, 줄 길이나 "다."로 끝나는지 같은 추측 규칙이 필요했고 문서마다 예외가 생겼다.

| | pypdf + 추측 규칙 | pdfplumber |
|---|---|---|
| 표를 못 찾은 페이지 | 29쪽 | 0쪽 |
| 정리 문단이 표에 붙은 페이지 | 처음 1,100쪽 → 고친 뒤 19쪽 | 0쪽 |
| 700자 넘는 청크 | 186개 | 0개 |

- **감수할 점**: PDF에 줄 끝 공백 정보가 없어 꺾인 줄을 이을 때 "한글-한글이면 붙인다"는 규칙을 쓴다. 원래 띄어 쓴 곳이 붙는 경우가 있다(`공식 부분` → `공식부분`). 반대로 공백으로 이으면 단어가 갈라진다(`무 료기간`). 표 칸 안의 줄바꿈은 서로 다른 값을 나누는 경우가 많아 공백으로 잇는다(그래서 `exa mple`처럼 단어 중간에 공백이 생기는 칸이 있다). 글자 크기 값은 이 데이터셋 기준이다.

### 2. 청크는 한 페이지 안에서, 구역 단위로 만든다

- **결정**: 페이지마다 설명 → 표 → 메모 → 정리 순서로 청크를 만든다. 모든 청크 앞에 `[문서 제목 > 장 제목 > 소제목]` 한 줄을 붙인다. 표는 행을 쪼개지 않고 700자까지 담고, 넘치면 새 청크에 맥락 줄·표 제목·머리글을 다시 붙인다. 설명·메모·정리는 문장 단위로 담는다. 오버랩은 쓰지 않는다.
- **이유**: 3,750쪽 모두 표가 정확히 하나씩 있고 머리글과 함께 그 페이지 안에서 끝난다. 한 페이지가 한 주제(소제목 하나)로 끝난다. 글자 수 + 오버랩으로 자르면 표 행이 중간에 잘린다. 맥락 줄은 청크 하나만 검색돼도 무슨 내용인지 알게 하려는 것으로, 본문에 넣는 이유는 임베딩과 키워드 검색이 본문만 보기 때문이다.
- **결과**: 청크 15,053개 (설명 3,750 / 표 6,247 / 메모 1,306 / 정리 3,750). e5 토크나이저 기준(접두사 포함) 512토큰을 넘는 청크 0개. 모든 청크가 `page_start == page_end`라 페이지 단위 평가에도 그대로 쓸 수 있다.
- `chunk_id`는 `<book_id>-p<page>-c<번호>`라서 같은 문서·내용·조건이면 항상 같다. 페이지 소제목·장 제목·구역 종류는 `metadata`의 `subtitle`·`section`·`kind`에 둔다.


## 테스트

```bash
uv run pytest packages/chunking
```
