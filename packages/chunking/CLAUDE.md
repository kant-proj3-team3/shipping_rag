# chunking — 청킹 모듈

## 범위

PDF 읽기, 청킹, 임베딩, Qdrant 색인, 인덱스 신원 기록, 평가용 골든 데이터셋 제공. 검색 로직과 LLM 호출은 하지 않는다.

## 제공 (`common.interfaces`)

`Embedder`, `Indexer`, `GoldenDatasetProvider`. 진입점: `create_embedder()`, `create_indexer(embedder)`, `create_golden_provider()`. 주입받는 것은 없다.

## 지킬 계약

- `book_id`는 파일명에서 `.pdf`를 뺀 값, 첫 페이지는 1쪽, 파일명은 바꾸지 않는다.
- 색인 payload는 `Chunk`(`model_dump(mode="json")`로 저장, `Chunk.model_validate`로 읽기). `page_start`~`page_end`는 실제로 걸친 페이지다.
- `chunk_id`는 결정적이다(같은 문서·내용·청킹 조건이면 같은 값). 모든 청크는 `manifest.max_chunk_tokens` 이하다.
- `embedder_id`는 모델·접두사·정규화·최대 길이까지 구분한다. 한도를 넘는 입력은 조용히 자르지 않는다(질의는 `InvalidInputError`, 문서는 `IngestError`).
- 빈 본문, 중복 `book_id`, 읽을 수 없는 PDF는 `manifest.failures`에 기록하고 색인에서 뺀다.
- 질문·정답·채점 기준은 색인하지 않는다. 골든셋은 서비스에 `question`만 전달되도록 `GoldenItem`으로 정규화해 평가기·러너에만 준다.
- 평가 파일 매핑은 `scripts/check_dataset_mapping.py`의 `raw_to_golden()`을 참고한다. `evidence_groups`는 그룹끼리 AND, 그룹 안 후보는 OR다.

## 데이터 특성 (참고)

- 문서마다 60~95페이지, 페이지당 약 600~1,800자. 모든 페이지에 같은 머리글(문서 ID·제목)과 하단 `n / N`이 반복된다.
- 표(업무 확인 대장)가 많고 비슷한 행이 많다. 정답 근거는 한 페이지 안에 있는 경우가 대부분이다.
- 정답 근거 페이지는 전체의 3.4%뿐이라 페이지 단위 정확도가 중요하다. PDF 제목은 `Chunk.title`로 쓴다.
- 인덱싱은 오래 걸린다. `progress` 콜백으로 진행을 알린다.

## 확인

`src/chunking/mock/`에 인터페이스를 만족하는 목업을 유지한다. 완료 전 `uv run pytest packages/chunking`과 `scripts/check_dataset_mapping.py`를 실행한다.
