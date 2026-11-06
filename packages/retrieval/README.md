# retrieval

세 가지 검색 방식(Naive / 하이브리드 / 하이브리드+리랭킹)을 구현하고, 검색 품질(Hit@k, Recall@k)을 평가한다. 청킹과 답변 생성은 하지 않는다.

> 현재 상태: **뼈대(목업)**. `create_*`는 `src/retrieval/mock/`의 목업을 돌려준다. 실제 구현은 아직 없다.

## 공개 인터페이스

| 진입점 | 반환 | 역할 |
|---|---|---|
| `create_retriever(embedder, index)` | `Retriever` | `retrieve(RetrievalRequest, RequestContext) -> RetrievalResult` (async). 방식은 `mode`로만 바꾼다 |
| `create_retrieval_evaluator(retriever)` | `RetrievalEvaluator` | `evaluate(items, mode, k, unit, golden_fingerprint=None) -> RetrievalReport` (async) |

주입받는 것: `Embedder`, `IndexManifest`(청킹 모듈 산출물). 설정은 환경변수로 읽는다.

## 지킬 계약 (요약)

- 결과는 길이 ≤ k, `rank`는 1부터 연속, `chunk_id` 중복 없음. 빈 결과는 정상이다.
- 세 방식은 같은 임베딩·저장소·k를 쓴다. 점수는 방식 간에 비교하지 않는다.
- 인덱스·임베더 불일치와 리랭커 입력 한도 불일치는 `IndexNotReadyError`, 그 외 실패는 `RetrievalError`, 질문이 임베더 한도를 넘으면 `InvalidInputError`를 그대로 전파한다.
- 평가는 근거 그룹 단위(그룹끼리 AND, 그룹 안 후보는 OR). `unit`(`document`/`page`)은 호출자가 명시한다. 근거 그룹이 없으면 `not_applicable`, 호출 실패는 `unavailable`이며 평균에서 제외하고 건수를 보고한다. 결과가 비어도 근거가 있는 문항은 0점으로 센다.
- `retriever.index`는 주입받은 `IndexManifest`다. 평가기와 백엔드가 인덱스 신원을 읽는 경로다.
- 정답·평가 정보를 검색에 쓰지 않고, Langfuse에 의존하지 않는다.

자세한 규칙은 [`CLAUDE.md`](CLAUDE.md)와 루트 [`CONTRACTS.md`](../../CONTRACTS.md)를 본다.

## 목업 (`src/retrieval/mock/`)

| 클래스 | 동작 |
|---|---|
| `MockRetriever` | 데모 청크 4개에서 단어 겹침으로 순위를 매긴다. 세 mode의 점수 척도만 다르게 흉내 낸다. 시작 시 `embedder_id` 일치와, 인덱스의 `max_chunk_tokens`가 목업 리랭커 입력 한도(512)를 넘지 않는지를 확인한다(위반 시 `IndexNotReadyError`) |
| `MockRetrievalEvaluator` | 실제 구현과 같은 규칙으로 Hit/Recall을 계산한다. 인덱스 신원은 `retriever.index`에서 읽고, `golden_fingerprint`는 호출자가 넘긴 값(없으면 `None`)을 보고서에 남긴다. 문항별 검색은 `asyncio.gather`로 병렬 호출한다 |

## 주요 설계 결정

- 아직 없음. 하이브리드 결합 방식(BM25 구현, 결합 점수), 리랭커 모델·입력 한도, 점수 임계값을 정하면 여기에 기록한다.

## 테스트

```bash
uv run pytest packages/retrieval
```
