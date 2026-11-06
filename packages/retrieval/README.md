# retrieval

세 가지 검색 방식(Naive / 하이브리드 / 하이브리드+리랭킹)을 구현하고, 검색 품질(Hit@k, Recall@k)을 평가한다. 청킹과 답변 생성은 하지 않는다.

> 현재 상태: **구현 중**. `create_*`는 아직 `src/retrieval/mock/`의 목업을 돌려준다. 세 방식이 모두 구현되기 전까지 목업을 유지한다.
>
> | 단계 | 상태 |
> |---|---|
> | 1. 설계 결정 (아래 '주요 설계 결정') | 완료 |
> | 2. Naive(Dense) 검색 (`dense.py`) | 구현·단위 테스트 완료. 아직 `create_retriever`에 연결하지 않았다 |
> | 3. 하이브리드 (BM25 + RRF) | 예정 |
> | 4. 하이브리드+리랭킹 | 예정 |
> | 5. 실제 평가기, `create_retriever` 연결 | 예정 |

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

## 파일 구성

| 파일 | 역할 |
|---|---|
| `src/retrieval/__init__.py` | 진입점 `create_retriever`, `create_retrieval_evaluator` (현재 목업을 돌려준다) |
| `src/retrieval/dense.py` | `DenseRetriever`: 질문을 임베딩해 Qdrant에서 top-k를 가져오는 Naive 검색 |
| `src/retrieval/store.py` | `create_qdrant_client()`: 환경변수로 Qdrant 클라이언트를 만든다 |
| `src/retrieval/mock/` | 인터페이스를 만족하는 목업 (아래) |
| `tests/test_dense.py` | `DenseRetriever` 단위 테스트 (Qdrant 메모리 모드, 자체 가짜 임베더) |
| `tests/test_retrieval_mock.py` | 목업의 계약 준수 테스트 |

## Naive 검색 동작 (`dense.py`)

1. 생성 시 `embedder.embedder_id`와 `index.embedder_id`가 다르면 `IndexNotReadyError`.
2. `retrieve`는 `embedder.embed_query`로 질문을 벡터로 바꾸고, `index.index_name` 컬렉션에서 가까운 k개를 가져온다. 임베딩과 Qdrant 호출은 동기라서 `asyncio.to_thread`로 돌린다.
3. payload는 `Chunk.model_validate`로 복원해 `RetrievedChunk(rank, score, chunk)`로 만든다. `rank`는 1부터 연속이고, 결과가 없으면 빈 목록(정상)이다.
4. 오류 처리: 질문이 임베더 한도를 넘는 `InvalidInputError` 같은 계약 오류는 그대로 전파하고, 그 밖의 Qdrant 오류와 payload 복원 실패는 `RetrievalError`로 감싼다. Naive가 아닌 mode는 `RetrievalError`다.

## 환경변수

모듈은 `.env`를 읽지 않고 환경변수만 본다(`.env`는 `app/`이 읽는다). 목록 원본은 루트 `.env.example`이다.

| 변수 | 쓰임 |
|---|---|
| `QDRANT_URL` | Qdrant 서버 주소 (기본 `http://localhost:6333`) |
| `QDRANT_PATH` | 서버 없이 단독 개발할 때만. 있으면 `QDRANT_URL`보다 우선하고 한 번에 한 프로세스만 쓴다 |
| `RERANKER_MODEL`, `RERANKER_MAX_TOKENS` | 리랭킹 방식에서 쓴다 (구현 예정) |

## 청킹 모듈과 맞춰야 할 전제

코드가 아래를 가정한다. 다르면 청킹 담당과 맞춘다.

- Qdrant 컬렉션 이름은 `manifest.index_name`이다.
- 벡터는 이름 없는 기본 벡터이고 거리 지표는 코사인이다.
- payload는 `Chunk` 스키마(`model_dump(mode="json")`)이고 `text`가 들어 있다.
- `manifest.max_chunk_tokens`는 리랭커 입력 한도(512) 이하다.

## 목업 (`src/retrieval/mock/`)

| 클래스 | 동작 |
|---|---|
| `MockRetriever` | 데모 청크 4개에서 단어 겹침으로 순위를 매긴다. 세 mode의 점수 척도만 다르게 흉내 낸다. 시작 시 `embedder_id` 일치와, 인덱스의 `max_chunk_tokens`가 목업 리랭커 입력 한도(512)를 넘지 않는지를 확인한다(위반 시 `IndexNotReadyError`) |
| `MockRetrievalEvaluator` | 실제 구현과 같은 규칙으로 Hit/Recall을 계산한다. 인덱스 신원은 `retriever.index`에서 읽고, `golden_fingerprint`는 호출자가 넘긴 값(없으면 `None`)을 보고서에 남긴다. 문항별 검색은 `asyncio.gather`로 병렬 호출한다 |

## 주요 설계 결정

아래 값은 초기 결정이다. 평가(`cli eval`)로 확인한 뒤 바꾸면 이 절도 함께 고친다.

### 0. 구조: `create_retriever` 하나가 세 방식을 모두 처리한다

- `dense.py`의 `DenseRetriever`(Naive)는 부품이다. 계약상 `create_retriever`가 돌려주는 검색기 하나가 세 `mode`를 모두 처리해야 하므로, 하이브리드·리랭킹이 구현되면 그 검색기가 이 부품을 쓴다.
- 시작 시 `manifest.max_chunk_tokens`와 리랭커 입력 한도(512) 대조는 그 상위 검색기에서 한다. 모드와 무관하게 시작 시점에 한 번 검사해 목업과 같은 동작을 유지한다.
- Qdrant 클라이언트는 `store.create_qdrant_client()`가 환경변수(`QDRANT_URL`, 단독 개발은 `QDRANT_PATH`)로 만들고, `create_retriever`가 부른다. 모듈은 `.env`를 읽지 않는다.
- 세 방식이 모두 구현되기 전까지 `create_retriever`는 목업을 돌려준다. Naive만 지원하는 검색기를 연결하면 세 방식을 비교하는 `cli eval`이 깨지기 때문이다.

### 1. BM25는 `rank_bm25`로 검색 모듈 안에서 처리한다

- **결정**: 시작 시 Qdrant 컬렉션의 모든 청크 `text`를 읽어(scroll) 메모리에 BM25 인덱스를 만든다.
- **이유**
  - 색인은 청킹 모듈의 일이다. Qdrant sparse vector는 청킹이 색인할 때 sparse vector까지 만들어 넣어야 해서 청킹 담당과의 협의·계약 조율이 필요하다. `rank_bm25`는 `Chunk.text`(계약 필수 필드)만 있으면 되므로 협의 없이 모듈 안에서 끝난다.
  - 규모가 작다(PDF 50개, 3,750페이지). 청크 수천~수만 개는 메모리 BM25로 충분하다.
  - 외부로 나가는 것은 `Retriever.retrieve()` 결과뿐이라, 나중에 sparse vector로 바꿔도 계약은 그대로다.
- **감수할 점**: 재색인 후에는 api를 재시작해야 BM25가 갱신된다(CLAUDE.md의 "인덱스 반영은 재시작" 규칙과 같다).

### 2. 결합 점수는 RRF(Reciprocal Rank Fusion)를 쓴다

- **결정**: Dense 순위와 BM25 순위를 `1 / (60 + 순위)`로 환산해 더한다. 상수 60은 RRF의 통상값이다.
- **이유**
  - Dense(코사인)와 BM25는 점수 척도가 달라 그대로 더할 수 없다. RRF는 순위만 쓰므로 정규화가 필요 없다.
  - 가중합의 α처럼 튜닝할 값이 거의 없어, 세 방식을 같은 조건에서 비교하는 평가가 공정하다.
  - 한쪽에서 순위가 높고 다른 쪽에서 낮은 청크도 후보에 남는다.
- **감수할 점**: 점수 크기 정보는 버린다. 평가 결과 가중합이 더 낫다고 나오면 그때 바꾼다.

### 3. 리랭커는 로컬 cross-encoder, 입력 한도는 512토큰

- **결정**: `RERANKER_MODEL`(환경변수, 기본값은 다국어를 지원하는 `BAAI/bge-reranker-v2-m3`)과 `RERANKER_MAX_TOKENS=512`. 하이브리드로 후보를 `k`보다 넉넉히 뽑은 뒤 질문·청크 쌍을 재채점해 상위 `k`개를 돌려준다.
- **이유**
  - 한국어 질문과 영문 해운 문서가 섞이므로 다국어 모델이 필요하다.
  - 임베딩을 로컬 E5로 쓰는 것과 같은 방식으로 로컬에서 돌려 외부 호출 비용·지연을 피한다.
  - 입력 한도를 보수적으로 512로 잡으면 청킹 담당이 맞추기 쉽고, 한도를 넘는 청크가 뒤에서 잘리는 일을 막을 수 있다.
- **청킹 모듈에 대한 전제**
  - 청크 `text`는 Qdrant payload에 반드시 들어 있어야 한다(BM25 입력).
  - `manifest.max_chunk_tokens`는 리랭커 한도 이하여야 한다. 넘으면 계약대로 `IndexNotReadyError`로 알린다. 청킹 담당에게 이 숫자(512)를 공유해야 한다.
- **감수할 점**: 후보 수만큼 모델을 돌려 지연이 늘어난다. 지연은 확인된 값만 보고서에 남긴다.

### 4. 점수 임계값은 방식별 내부 설정으로 두고 기본은 끈다

- **결정**: 방식(Naive / 하이브리드 / 리랭킹)마다 따로 환경변수로 받는 내부 설정이다. 기본값은 "임계값 없음"이다.
- **이유**
  - 코사인·BM25·RRF·리랭커 점수는 척도가 달라 공통 임계값을 둘 수 없다. 공통 계약에 넣으면 방식 간 점수를 비교하는 것처럼 오해하게 된다(CLAUDE.md: 점수는 방식 간에 직접 비교하지 않는다).
  - 기본을 끄면 세 방식이 같은 `k`로 비교되고, 빈 결과는 실패가 아니라는 계약과도 충돌하지 않는다.
  - 임계값은 평가 결과를 본 뒤 필요하면 켠다.

## 테스트

```bash
uv run pytest packages/retrieval
```
