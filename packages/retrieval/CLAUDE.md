# retrieval — 검색 모듈

## 범위

세 가지 검색 방식 구현(Naive / 하이브리드 / 하이브리드+리랭킹)과 검색 품질 평가(Hit@k, Recall@k). 청킹, 답변 생성은 하지 않는다.

## 제공 (`common.interfaces`)

`Retriever`, `RetrievalEvaluator`. 진입점: `create_retriever(embedder, index)`, `create_retrieval_evaluator(retriever)`. 주입받는 것: `Embedder`, `IndexManifest`.

## 지킬 계약

- 방식은 `mode`로만 바꾼다. 서비스를 따로 만들지 않는다. 세 방식은 같은 임베딩·저장소·k를 쓴다.
- 결과는 길이 ≤ k, `rank`는 1부터 연속, `chunk_id` 중복 없음. **빈 결과는 정상**이다.
- 인덱스·임베더 불일치는 `IndexNotReadyError`, 그 외 실패는 `RetrievalError`. 질문이 임베더 한도를 넘으면 `InvalidInputError`를 그대로 전파한다.
- `Retriever.index`는 주입받은 `IndexManifest` 그대로 노출한다(평가기·백엔드가 인덱스 신원을 읽는 경로).
- 시작 시 `manifest.max_chunk_tokens`를 자기 리랭커 입력 한도와 대조한다. 안 맞으면 `IndexNotReadyError`(조용히 자르지 않는다).
- 점수 임계값은 방식마다 척도가 달라 내부 설정이다. 점수는 방식 간 비교하지 않는다.
- 정답·평가 정보를 참조하지 않는다. Langfuse에 의존하지 않는다(기록은 백엔드가 한다).
- `RetrievalEvaluator.evaluate(items, mode, k, unit, golden_fingerprint=None)`:
  - 근거 그룹 단위. 그룹이 만족되면 satisfied. Hit = 만족한 그룹이 하나라도 있으면 1, Recall = 만족한 그룹 수 / 전체 그룹 수.
  - `unit=document`는 `book_id` 일치, `unit=page`는 청크의 `[page_start, page_end]`가 근거 페이지를 포함해야 일치. `unit`은 호출자가 명시한다.
  - 근거 그룹이 없는 문항은 `not_applicable`, 호출 실패는 `unavailable`(둘 다 평균에서 제외하고 건수 보고). 결과가 비어도 근거가 있는 문항은 0점으로 센다.
  - 보고서에 `unit`, `index_name`, `index_fingerprint`(`retriever.index`에서), `golden_fingerprint`(호출자가 인자로 넘긴 값)를 남긴다.

## 데이터 특성 (참고)

- 근거 그룹은 문항당 최대 7개. `k`가 그룹 수보다 작으면 Recall 만점이 불가능하니 보고서의 `k`와 함께 해석한다.
- 비슷한 표 행이 많아 고유 식별자(예약·장비 번호) 일치가 중요하다. 그래서 BM25 결합의 가치가 클 수 있다.

## 확인

`src/retrieval/mock/`에 인터페이스를 만족하는 목업을 유지한다. 완료 전 `uv run pytest packages/retrieval`을 실행한다.
