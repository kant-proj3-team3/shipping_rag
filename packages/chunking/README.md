# chunking

PDF를 읽어 청킹하고, 임베딩해 Qdrant에 색인하고, 인덱스의 신원(`IndexManifest`)을 기록한다. 평가용 골든 데이터셋(`GoldenItem`)도 이 모듈이 정규화해 제공한다. 검색 로직과 LLM 호출은 하지 않는다.

> 현재 상태: **실제 구현 있음, 기본값은 목업**. `CHUNKING_IMPL=real`이면 실제 구현을, 없으면 `src/chunking/mock/`의 목업을 돌려준다. 실제 구현은 PDF·모델·Qdrant가 필요해서, CI와 다른 모듈의 개발이 깨지지 않도록 기본값을 목업으로 둔다.

## 공개 인터페이스

`common.interfaces`의 Protocol 세 개를 제공한다. 진입점은 `common.entrypoints`의 시그니처를 따른다.

| 진입점 | 반환 (실제 구현) | 역할 |
|---|---|---|
| `create_embedder()` | `Embedder` (`E5Embedder`) | 텍스트 → 벡터. 검색·평가 모듈에 주입된다 |
| `create_indexer(embedder)` | `Indexer` (`PdfIndexer`) | `build(IndexBuildRequest) -> IndexManifest`, `get_manifest(index_name)` |
| `create_golden_provider()` | `GoldenDatasetProvider` (`EvaluationGoldenProvider`) | `load(splits)`, `fingerprint(splits)` |

주입받는 것은 없다.

## 환경변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `CHUNKING_IMPL` | `mock` | `real`이면 실제 구현 |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-base` | 임베딩 모델 |
| `EMBEDDING_MAX_TOKENS` | `512` | 접두사를 포함한 입력 상한. 바꾸면 `embedder_id`가 바뀐다 |
| `EMBEDDING_DEVICE` | (자동) | `cuda` / `cpu`. 비우면 GPU가 있으면 `cuda` |
| `EMBEDDING_BATCH_SIZE` | `64` | GPU 메모리가 부족하면 줄인다 |
| `RAG_MODEL_CACHE` | (라이브러리 기본) | 모델 다운로드 위치 |
| `CHUNK_MAX_CHARS` | `700` | 청크 최대 글자 수 |
| `QDRANT_URL` / `QDRANT_PATH` | `http://localhost:6333` / 없음 | `QDRANT_PATH`가 있으면 서버 없는 로컬 모드 (단독 개발용). 로컬 모드는 한 번에 한 프로세스만 열 수 있다. 색인과 api를 함께 쓰려면 Qdrant 서버(`QDRANT_URL`)를 쓴다 |
| `DOCUMENTS_DIR` / `EVALUATION_DIR` | `./data/documents` / `./data/evaluation` | 골든셋 점검에 쓴다 (색인 폴더는 `IndexBuildRequest.documents_dir`) |

## 실행

```bash
# .env 에 CHUNKING_IMPL=real, INDEX_NAME=rag-dev-<본인이름> 을 넣은 뒤
docker compose up -d qdrant
uv run python -m app.cli index            # 같은 index_name 이 있으면 --rebuild 로만 덮어쓴다
```

## 파일 구성

| 파일 | 역할 |
|---|---|
| `pdf_parser.py` | pdfplumber로 PDF 페이지를 구역(제목·설명·표·메모·정리)으로 나눈다 |
| `chunker.py` | 페이지 구역 → `Chunk` |
| `embedder.py` | E5 임베더 |
| `qdrant_store.py` | Qdrant 컬렉션과 manifest 저장 |
| `indexer.py` | 위 단계를 묶어 색인한다 (parse → chunk → embed → upsert) |
| `golden.py` | 평가 파일 → `GoldenItem` |
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

- **감수할 점**: PDF에 줄 끝 공백 정보가 없어 꺾인 줄을 이을 때 "한글-한글이면 붙인다"는 규칙을 쓴다. 원래 띄어 쓴 곳이 붙는 경우가 있다(`공식 부분` → `공식부분`). 반대로 공백으로 이으면 단어가 갈라진다(`무 료기간`). 표 칸 안의 줄바꿈은 서로 다른 값을 나누는 경우가 많아 공백으로 잇는다. 단, 칸 폭 때문에 꺾인 이메일(`vgm@gaonroute.exa` + `mple`)은 공백 없이 붙인다(이전에는 표 칸 이메일 726곳이 `exa mple`처럼 갈라져 키워드 검색과 답변에서 주소가 빠졌다). 글자 크기 값은 이 데이터셋 기준이다.

### 2. 청크는 한 페이지 안에서, 구역 단위로 만든다

- **결정**: 페이지마다 설명 → 표 → 메모 → 정리 순서로 청크를 만든다. 모든 청크 앞에 `[문서 제목 > 장 제목 > 소제목]` 한 줄을 붙인다. 표는 행을 쪼개지 않고 700자까지 담고, 넘치면 새 청크에 맥락 줄·표 제목·머리글을 다시 붙인다. 설명·메모·정리는 문장 단위로 담는다. 오버랩은 쓰지 않는다.
- **이유**: 3,750쪽 모두 표가 정확히 하나씩 있고 머리글과 함께 그 페이지 안에서 끝난다. 한 페이지가 한 주제(소제목 하나)로 끝난다. 글자 수 + 오버랩으로 자르면 표 행이 중간에 잘린다. 맥락 줄은 청크 하나만 검색돼도 무슨 내용인지 알게 하려는 것으로, 본문에 넣는 이유는 임베딩과 키워드 검색이 본문만 보기 때문이다.
- **결과**: 청크 15,053개 (설명 3,750 / 표 6,247 / 메모 1,306 / 정리 3,750). e5 토크나이저 기준(접두사 포함) 512토큰을 넘는 청크 0개. 모든 청크가 `page_start == page_end`라 페이지 단위 평가에도 그대로 쓸 수 있다.
- `chunk_id`는 `<book_id>-p<page>-c<번호>`라서 같은 문서·내용·조건이면 항상 같다. 페이지 소제목·장 제목·구역 종류는 `metadata`의 `subtitle`·`section`·`kind`에 둔다.

### 3. 임베딩은 multilingual-e5-base

- **결정**: `intfloat/multilingual-e5-base`, 문서 `passage: ` / 질의 `query: `, L2 정규화, 최대 512토큰.
- **이유**: 같은 청크로 small/base/large를 의미 검색만으로 비교했다 (질문 56개, 근거 없는 4개 제외, 문서 단위). k=5에서 base가 가장 좋았고 large보다 색인은 3.3배, 검색은 1.6배 빨랐다.

| 모델 | Hit@5 | Recall@5 | 색인 시간 (RTX 5060) |
|---|---|---|---|
| small | 0.946 | 0.653 | 30초 |
| base | 1.000 | 0.711 | 87초 |
| large | 0.982 | 0.684 | 288초 |

  이 표는 팀 평가기(근거 그룹 단위) 이전의 개인 실험 지표라 팀 보고서 숫자와 직접 비교하지 않는다.
- `count_tokens`는 문서 접두사를 붙인 길이(특수 토큰 포함)를 센다. 인덱서는 이 값으로 모든 청크가 `max_input_tokens` 이하인지 확인하고, 넘는 청크는 `failures`에 기록하고 뺀다.

### 4. manifest는 Qdrant의 별도 컬렉션에 저장한다

- **결정**: 청크 컬렉션 이름은 `index_name`(이름 없는 기본 벡터, 코사인). manifest는 `<index_name>__manifest` 컬렉션의 점 하나에 저장한다. 점 id는 `chunk_id`로 만든 UUID다.
- **이유**: api·cli가 다른 프로세스에서도 `get_manifest`로 같은 값을 읽어야 한다. 청크 컬렉션에 섞으면 검색 모듈이 BM25용으로 모든 점을 `Chunk`로 읽을 때 깨진다.
- 임베딩이 끝난 뒤 기존 인덱스를 지우고 쓴다(재색인 도중 실패해도 이전 인덱스가 먼저 사라지지 않게). manifest는 맨 마지막에 저장한다.
- 색인할 청크가 0개면(폴더 경로 오류, PDF 없음, 전부 실패) 기존 인덱스를 지우기 전에 `IngestError`로 멈춘다. 빈 인덱스가 "준비된 인덱스"로 보이지 않게 하려는 것이다.
- Qdrant 클라이언트를 닫는 `close()`는 두지 않는다. 클라이언트를 언제 열고 닫을지는 그것을 쓰는 쪽(api·cli)이 정한다. 로컬 모드(`QDRANT_PATH`)에서 여러 요청이 같은 저장소를 쓰지 않도록 막는 잠금(락)도 백엔드가 맡는다. 필요해지면 `close()`를 추가한다.
- `manifest.max_chunk_tokens`는 임베더 한도(512)다. 실제 최대 토큰 수는 `params.observed_max_chunk_tokens`에 남긴다.

### 5. 골든셋은 평가 파일을 그대로 정규화하고 점검한다

- **결정**: `scripts/check_dataset_mapping.py`의 `raw_to_golden()`과 같은 매핑. id 중복, `*_questions.json`과의 id·질문 일치, 근거 `book_id`·`page`가 실제 PDF 범위 안인지 확인하고, 어긋나면 `IngestError`.
- **결과**: 기본 60문항(보안 포함 62문항), 근거 189곳. 근거 `quote` 189곳이 모두 해당 페이지의 청크 안에 있다(띄어쓰기·`|` 무시).

## 테스트

```bash
uv run pytest packages/chunking
```

`tests/test_chunking_real.py`는 PDF·모델·Qdrant 서버 없이 돈다 (가짜 페이지 구역, 가짜 모델, 메모리 Qdrant).
