# retrieval

세 가지 검색 방식(Naive / 하이브리드 / 하이브리드+리랭킹)을 구현하고, 검색 품질(Hit@k, Recall@k)을 평가한다. 청킹과 답변 생성은 하지 않는다.

> 현재 상태: **구현 완료, 실제 색인으로 평가함**. 세 검색 방식(Naive `dense.py`, 하이브리드 BM25 + RRF `hybrid.py`, 하이브리드+리랭킹 `reranker.py`)과 근거 그룹 평가기(`evaluator.py`)를 구현했고, 실제 색인(`rag-dev-chanyeongg3`, 청크 15,053개)과 골든 60문항(채점 56문항)으로 `document`·`page` 단위, k=5·10·20을 평가했다. 결과는 아래 '평가 결과'와 [`report/retrieval_quality_report.md`](report/retrieval_quality_report.md)에 있다. 단위 테스트는 메모리 Qdrant, 가짜 청크, **가짜 리랭커**, 가짜 검색기로 한다. 모듈의 기본값은 목업이고, 환경변수 `RETRIEVAL_IMPL=real`일 때만 실제 구현을 돌려준다. app(api·cli)은 `APP_IMPL`(기본 `real`)이 이 값을 채우므로 앱에서는 실제 구현이 기본이다.

## 공개 인터페이스

| 진입점 | 반환 | 역할 |
|---|---|---|
| `create_retriever(embedder, index)` | `Retriever` | `retrieve(RetrievalRequest, RequestContext) -> RetrievalResult` (async). 방식은 `mode`로만 바꾼다 |
| `create_retrieval_evaluator(retriever)` | `RetrievalEvaluator` | `evaluate(items, mode, k, unit, golden_fingerprint=None) -> RetrievalReport` (async) |

주입받는 것: `Embedder`, `IndexManifest`(청킹 모듈 산출물). 설정은 환경변수(`RETRIEVAL_IMPL`, `QDRANT_URL`, 단독 개발은 `QDRANT_PATH`, 리랭킹은 `RERANKER_MODEL`·`RERANKER_MAX_TOKENS`)로 읽는다. `RETRIEVAL_IMPL`이 없으면 `mock`이고 `real`이면 실제 구현이다. 리랭킹 변수가 없으면 기본값(`BAAI/bge-reranker-v2-m3`, 512)을 쓴다.

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

아래 값은 초기 결정이고, 평가(`cli eval`)로 확인한 결과는 각 절의 '확인' 항목에 덧붙였다. 결정을 바꾸면 이 절도 함께 고친다.

### 0. Naive(Dense)는 `dense.py`의 부품으로 두고, 검색기는 하나로 통합한다

- **결정**
  - `DenseRetriever`(`dense.py`)는 질문을 `embed_query`로 벡터로 바꿔 `index.index_name` 컬렉션에서 가까운 k개를 가져오고, payload를 `Chunk`로 복원해 `RetrievedChunk(rank, score, chunk)`를 만든다.
  - 오류는 계약대로 나눈다: 임베더 id 불일치는 `IndexNotReadyError`, 질문이 임베더 한도를 넘는 `InvalidInputError`는 그대로 전파, 그 밖의 Qdrant 오류와 payload 복원 실패는 `RetrievalError`다. Naive가 아닌 mode를 받으면 `RetrievalError`다.
  - 동기인 임베딩·Qdrant 호출은 `asyncio.to_thread`로 돌려 이벤트 루프를 막지 않는다.
  - Qdrant 클라이언트는 `store.create_qdrant_client()`가 환경변수(`QDRANT_URL`, 단독 개발은 `QDRANT_PATH`)로 만든다. 모듈은 `.env`를 읽지 않는다.
  - 최종 검색기는 `create_retriever`가 돌려주는 하나의 객체이고, 이 부품을 안에서 쓴다. 현재 `hybrid.py`의 `HybridRetriever`가 `naive`, `hybrid`, `hybrid_rerank`를 모두 처리한다. 시작 시 `manifest.max_chunk_tokens`와 리랭커 입력 한도(512) 대조도 그 객체가 모드와 무관하게 한 번 한다.
- **이유**
  - 계약상 세 방식은 `mode`로만 바뀌고 같은 임베딩·저장소·k를 쓴다. 검색기를 따로 만들면 이 조건을 지키기 어렵다.
  - 목업과 같은 오류 규칙을 지켜야 백엔드가 `InvalidInputError`를 400으로 매핑할 수 있다.
- **전제(청킹 모듈)**: 컬렉션 이름은 `manifest.index_name`, 벡터는 이름 없는 기본 벡터, 거리 지표는 코사인이다. 다르면 청킹 담당과 맞춘다.
- **연결(`__init__.py`)**: `RETRIEVAL_IMPL=real`이면 `create_retriever`가 `store.create_qdrant_client()`로 만든 클라이언트와 `HybridRetriever`를, `create_retrieval_evaluator`가 `GroupRetrievalEvaluator`를 돌려준다. 그 밖에는 목업이다. 실제 구현은 필요할 때만 불러서, 목업만 쓸 때는 qdrant·torch를 읽지 않는다.
- **감수할 점**: 기본값이 목업인 이유는 실제 색인이 없는 환경에서 `cli eval`과 api 시연이 깨지지 않게 하기 위해서다. `real`은 컬렉션이 없으면 `IndexNotReadyError`이다. 실제 색인(15,053청크)으로 검색과 평가를 돌려 확인했다.

### 1. BM25는 `rank_bm25`로 검색 모듈 안에서 처리한다

- **결정**: 시작 시 Qdrant 컬렉션의 모든 청크 `text`를 읽어(scroll) 메모리에 BM25 인덱스를 만든다.
- **이유**
  - 색인은 청킹 모듈의 일이다. Qdrant sparse vector는 청킹이 색인할 때 sparse vector까지 만들어 넣어야 해서 청킹 담당과의 협의·계약 조율이 필요하다. `rank_bm25`는 `Chunk.text`(계약 필수 필드)만 있으면 되므로 협의 없이 모듈 안에서 끝난다.
  - 규모가 작다(PDF 50개, 3,750페이지). 청크 수천~수만 개는 메모리 BM25로 충분하다.
  - 외부로 나가는 것은 `Retriever.retrieve()` 결과뿐이라, 나중에 sparse vector로 바꿔도 계약은 그대로다.
- **구현(`hybrid.py`)**: `HybridRetriever`가 `naive`, `hybrid`, `hybrid_rerank`를 처리한다(리랭킹은 3번). 생성할 때 `load_chunks`가 컬렉션의 청크를 읽어 BM25 인덱스를 만들고(청크가 없으면 BM25 없이 빈 결과), 컬렉션이 없거나, 읽기에 실패하거나, payload가 `Chunk` 형식과 맞지 않으면 `IndexNotReadyError`다(시작 시점의 색인 형식 불일치는 "인덱스 준비 안 됨"으로 본다. 질의 중 `dense.py`의 같은 실패는 `RetrievalError`). 색인 형식에 의존하는 곳은 `load_chunks` 하나다. 토큰화는 소문자 변환 후 `\w+(-\w+)*`로 자르며, `R-0021` 같은 식별자는 한 토큰으로 둔다.
- **감수할 점**
  - 재색인 후에는 api를 재시작해야 BM25가 갱신된다(CLAUDE.md의 "인덱스 반영은 재시작" 규칙과 같다).
  - 토큰화는 가장 단순한 방식이라 한국어 조사가 붙은 단어는 못 찾을 수 있다(`정정합니다` ↔ `정정은`). 시작 시 청크 15,053개를 읽어 BM25를 만드는 데 조립과 청크 로드를 합쳐 약 13초가 걸린다(CPU 환경에서 측정, `latency_ms`에는 들어가지 않는다).
  - **확인(토큰화)**: 조사 분리(규칙)와 형태소 분석(Kiwi)을 같은 조건(page, k=5·10·20)으로 시험했다. BM25 단독 순위는 좋아졌지만(근거 그룹 178개 중 BM25 50위 안이 133개에서 Kiwi 144개) 최종 Hit·Recall 변화는 대부분 ±0.02 안이고 DEV·ADD 방향이 엇갈려, 현재 토큰화를 유지한다(보고서 5.3). 이 비교는 page 기준이고 document 기준은 확인하지 않았다.
  - **확인(파라미터·전처리)**: 길이 보정 `b`, `k1`, BM25+, 머리글 제외, 흔한 단어 제외를 하나씩 바꿔 비교했다. 길이 보정을 약하게 하면(`b=0.3`) hybrid Recall이 +0.009~+0.015 오르지만 hybrid_rerank는 거의 변하지 않아 아직 적용하지 않았다. 이 실험 기록은 저장소에 올리지 않았다.
  - 후보 수는 방식마다 50개로 고정이다. `RetrievalRequest.k`의 상한(50) 때문에 Dense 후보를 `retrieve`로 가져올 때 그 값을 넘길 수 없다.

### 2. 결합 점수는 RRF(Reciprocal Rank Fusion)를 쓴다

- **결정**: Dense 순위와 BM25 순위를 `1 / (60 + 순위)`로 환산해 더한다. 상수 60은 RRF의 통상값이다.
- **이유**
  - Dense(코사인)와 BM25는 점수 척도가 달라 그대로 더할 수 없다. RRF는 순위만 쓰므로 정규화가 필요 없다.
  - 가중합의 α처럼 튜닝할 값이 거의 없어, 세 방식을 같은 조건에서 비교하는 평가가 공정하다.
  - 한쪽에서 순위가 높고 다른 쪽에서 낮은 청크도 후보에 남는다.
- **감수할 점**: 점수 크기 정보는 버린다. 평가 결과 가중합이 더 낫다고 나오면 그때 바꾼다.
- **확인**: BM25 순위가 좋아져도 최종 지표가 같이 움직이지 않았다(위 1번의 토큰화 비교). 결합 단계(같은 가중치, 상수 60)의 영향은 확인하지 않았고, 조정 여부는 후속 과제다.

### 3. 리랭커는 로컬 cross-encoder, 입력 한도는 512토큰

- **결정**: `RERANKER_MODEL`(환경변수, 기본값은 다국어를 지원하는 `BAAI/bge-reranker-v2-m3`)과 `RERANKER_MAX_TOKENS=512`. 하이브리드로 후보를 `k`보다 넉넉히 뽑은 뒤 질문·청크 쌍을 재채점해 상위 `k`개를 돌려준다.
- **구현(`reranker.py`)**: `CrossEncoderReranker`가 (질문, 청크 본문) 쌍에 점수를 매긴다. 후보는 RRF 결합 결과의 상위 50개(`CANDIDATE_POOL`)이고, 점수가 높은 순(동점이면 `chunk_id` 순)으로 상위 `k`개를 고른다. 모델은 처음 점수를 매길 때 읽고, 여러 요청이 동시에 불러도 안전하도록 로딩과 호출에 잠금을 둔다. 리랭커 오류는 `RetrievalError`로 감싸고 `InvalidInputError` 같은 계약 오류는 그대로 전파한다. 테스트는 `scorer`를 주입한 가짜 리랭커로 한다.
- **이유**
  - 한국어 질문과 영문 해운 문서가 섞이므로 다국어 모델이 필요하다.
  - 임베딩을 로컬 E5로 쓰는 것과 같은 방식으로 로컬에서 돌려 외부 호출 비용·지연을 피한다.
  - 입력 한도를 보수적으로 512로 잡으면 청킹 담당이 맞추기 쉽고, 한도를 넘는 청크가 뒤에서 잘리는 일을 막을 수 있다.
- **청킹 모듈에 대한 전제**
  - 청크 `text`는 Qdrant payload에 반드시 들어 있어야 한다(BM25 입력).
  - `manifest.max_chunk_tokens`는 리랭커 한도 이하여야 한다. 넘으면 계약대로 `IndexNotReadyError`로 알린다. 청킹 담당에게 이 숫자(512)를 공유해야 한다.
- **감수할 점**
  - 후보 수만큼 모델을 돌려 지연이 늘어난다. 지연은 확인된 값만 보고서에 남긴다.
  - 한도 대조는 `max_chunk_tokens`와 리랭커 한도(512)의 설정값 비교다. 실제 질문과 청크를 합친 길이를 세지는 않으므로 질문이 길면 합친 길이가 한도를 넘을 수 있다.
  - CPU torch(`2.15.0+cpu`)에서는 실제 모델이 느렸다. 이후 dev에서 팀원이 Windows용 CUDA 12.8 빌드 torch를 설정했다(PR #29). `CrossEncoder`에는 device를 따로 지정하지 않으며, GPU가 잡히면 모델이 `cuda:0`에 올라간다(torch 2.14.1+cu130 환경에서 확인).
- **실제 모델 확인 결과**(2026-11-08, CPU, 임시 청킹 결과 `chunks.json`의 청크 15,053개와 질문 1개로 측정)
  - 모델 로딩과 점수 계산이 된다. 첫 호출은 모델 다운로드를 포함해 59.3초, 이후 3쌍은 110ms였다.
  - 직접 쓴 예시 3쌍에서 정답에 가까운 표 행 청크가 0.999, 같은 터미널의 다른 내용이 0.005, 다른 문서가 0.000이었다. 순서가 말이 되는지만 본 것이고 품질 평가가 아니다.
  - 토큰 길이: 청크만 최대 430, 질문과 합쳐 최대 453이고 512를 넘는 청크는 0개였다. 청킹 쪽 기준(e5 토크나이저, `passage: ` 포함)은 최대 432로 리랭커 토크나이저와 거의 같았다. 이 질문보다 긴 질문이면 여유가 줄 수 있다.
  - 속도: 후보 50개를 재채점하는 데 중앙값 길이 청크는 3.8초, 가장 긴 청크 50개는 14.9초가 걸렸다. 질문 하나당 이만큼 늘어난다. 모델 호출에 잠금이 있어 문항을 동시에 검색해도 줄지 않는다.
- **실제 색인 평가에서 확인한 것**(2026-11-09~11, 정식 색인, 채점 56문항)
  - 순위 품질: `hybrid_rerank`가 `page`·`document` 모두 모든 k에서 Recall이 가장 높다(아래 '평가 결과'). 리랭커는 후보 50개의 순서만 바꾸므로 k가 커질수록 하이브리드와의 차이가 줄고, document k=20에서는 사실상 같다.
  - 입력 길이: 평가에서 리랭커에 실제로 들어간 질문+청크 쌍 2,800개(56문항 × 후보 50개) 중 가장 긴 것이 504토큰이라 512에서 잘린 쌍이 없었다. 입력 한도를 512 / 1024 / 2048로 바꿔도 Hit@5, Recall@5, 문항별 점수, 상위 5개 순위가 모두 같았다(page, k=5). 그래서 512를 유지한다. 가장 긴 쌍과 한도의 여유는 8토큰뿐이므로 청크나 질문이 길어지면 다시 잰다.
  - 속도(GPU, RTX 5060 Laptop, torch 2.14.1+cu130): 질문 1개(후보 50쌍 = 배치 32 + 18)에 평균 1.28초(0.83~1.79초), 모델 로딩과 첫 호출은 4.63초다. 평가 60문항은 약 78초(질문당 약 1.3초)다. 최초 평가는 109~119초가 걸렸는데 이유는 확인하지 않았다. CPU에서는 같은 평가가 798.5초(GPU 평가와 동시에 돌려 참고용)였고, api와 같은 CPU 환경에서 질문 1개가 8~17초 걸렸다.
  - 동시 요청: 리랭커 호출은 잠금으로 한 번에 하나씩 처리된다. 요청이 몰리면 뒤 요청의 `latency_ms`에 앞 요청을 기다린 시간이 포함된다(CPU에서 3개 동시 요청이 15.3 / 36.3 / 22.8초). 평가기가 문항 8개를 동시에 보내도 전체 시간은 순서대로 돌린 것과 비슷하다.
  - 시험하지 않은 것: 후보 수(50) 줄이기, 시작 시 모델 미리 불러오기, fp16.

### 4. 점수 임계값은 방식별 내부 설정으로 두고 기본은 끈다

- **결정**: 방식(Naive / 하이브리드 / 리랭킹)마다 따로 환경변수로 받는 내부 설정이다. 기본값은 "임계값 없음"이다. 아직 구현하지 않았다(기본값이 '없음'이라 현재 동작은 같다). 필요해지면 평가 결과를 보고 추가한다.
- **이유**
  - 코사인·BM25·RRF·리랭커 점수는 척도가 달라 공통 임계값을 둘 수 없다. 공통 계약에 넣으면 방식 간 점수를 비교하는 것처럼 오해하게 된다(CLAUDE.md: 점수는 방식 간에 직접 비교하지 않는다).
  - 기본을 끄면 세 방식이 같은 `k`로 비교되고, 빈 결과는 실패가 아니라는 계약과도 충돌하지 않는다.
  - 임계값은 평가 결과를 본 뒤 필요하면 켠다.

### 5. 평가기는 근거 그룹 단위로 계산하고, 실패와 해당 없음은 평균에서 뺀다

- **결정**(`evaluator.py`의 `GroupRetrievalEvaluator`)
  - 문항마다 `item.question`만 검색에 넘기고, 근거 그룹은 채점에만 쓴다. 그룹 안 후보 중 하나라도 어느 청크와 일치하면 그 그룹은 만족이다(그룹끼리 AND, 그룹 안 OR). Hit = 만족한 그룹이 하나라도 있으면 1, Recall = 만족한 그룹 수 / 전체 그룹 수다. 만족 여부는 그룹 번호로 기록하므로 같은 근거가 여러 청크에서 나와도 한 번만 센다.
  - `unit`은 호출자가 명시한다. `document`는 `book_id`가 같으면, `page`는 청크의 `[page_start, page_end]`가 근거 페이지를 포함하면 일치다.
  - 근거 그룹이 없는 문항은 검색하지 않고 `not_applicable`, 검색 호출이 실패한 문항은 `unavailable`이며 둘 다 평균에서 빼고 건수를 보고한다. 검색 결과가 비어도 근거가 있는 문항은 0점으로 센다. 평가할 문항이 하나도 없으면 평균은 0이 아니라 `None`이다.
  - 검색 호출이 `IndexNotReadyError`(인덱스·설정 문제)로 실패하면 문항별로 삼키지 않고 평가를 중단한다. 이 문제는 모든 문항에 똑같이 생기기 때문이다. 그 밖의 예외는 해당 문항만 `unavailable`로 기록하고, 채점할 문항이 모두 실패하면 `RetrievalError`로 알린다(평균이 `None`인 보고서를 정상 결과처럼 내지 않기 위해서다).
  - 보고서에 `unit`, `index_name`, `index_fingerprint`(`retriever.index`에서), `golden_fingerprint`(호출자가 넘긴 값)를 남긴다.
  - `k`가 1 미만이거나 50(`RetrievalRequest.k`의 상한)을 넘으면 평가를 시작하기 전에 `ValueError`로 막는다. 문항을 동시에 8개까지만 검색하고, `max_concurrency`를 1 미만으로 주면 생성할 때 `ValueError`다(세마포어가 0이면 평가가 영원히 멈추기 때문이다).
- **이유**
  - 잘못된 `k`를 그대로 두면 모든 문항의 검색이 실패해 모두 `unavailable`이 되고 원인이 가려진다.
  - 임베더와 리랭커가 한꺼번에 몰리지 않도록 동시 검색 수를 제한한다.
  - 미확인 값을 0으로 채우지 않는다는 규칙(`None`, `not_applicable`, `unavailable`)을 지킨다.
- **감수할 점**
  - 목업 평가기(`mock/evaluator.py`)와 계산 규칙이 거의 같아 중복이 있다. CLAUDE.md의 "목업을 유지한다"는 규칙에 따라 그대로 두었다.
  - `IndexNotReadyError` 외의 예외(`RetrievalError`, 코드 오타 같은 예상 밖의 오류)는 문항 실패로 가려질 수 있다. 보고서의 `unavailable` 건수와 사유(`reason`)를 함께 확인한다. 이 규칙은 처음에는 모든 예외를 `unavailable`로 처리했다가, 리뷰(PR #19)에서 설정 오류가 가려진다는 지적을 받아 지금처럼 바꿨다.
  - 실제 색인과 골든 데이터로 평가했다(아래 '평가 결과'). 근거가 한 문서·페이지뿐인 문항은 같은 뜻의 다른 페이지를 찾아도 page 기준에서는 0점이다(예: `IS-ADD-10`).
  - `hybrid_rerank`는 문항마다 리랭킹 시간이 더해진다. 60문항 평가가 GPU에서 약 78초, CPU에서 798.5초였다(위 3번의 측정값).

## 평가 결과

실제 색인으로 평가한 요약이다. 전체 표, DEV/ADD 분리, 근거 그룹 수별 Recall, 실패 사례는 [`report/retrieval_quality_report.md`](report/retrieval_quality_report.md)를 본다.

| 항목 | 값 |
|---|---|
| 인덱스 | `rag-dev-chanyeongg3`, 청크 15,053개, `intfloat/multilingual-e5-base` |
| `index_fingerprint` | `0acd52b3e8804b0d6e07c54dfa396f2d8b01a05402f912b1ceeeca481edbe2f4` |
| `golden_fingerprint` | `6fb91800a14772fdf63c158d760323b6864d8979f8f9ec1f7fbf3210cb7b1bef` |
| 문항 | 60개 중 채점 56개(근거 그룹 없음 4개), 검색 실패 0건 |
| 실행 환경 | GPU, torch 2.14.1+cu130 |

각 칸은 `Hit@k / Recall@k`다.

**page**

| 방식 | k=5 | k=10 | k=20 |
|---|---|---|---|
| Naive | 0.911 / 0.619 | 0.982 / 0.689 | 0.982 / 0.733 |
| 하이브리드 | 0.875 / 0.596 | 0.946 / 0.700 | 0.982 / 0.794 |
| 하이브리드+리랭킹 | **0.964 / 0.676** | **0.982 / 0.765** | **0.982 / 0.808** |

**document**

| 방식 | k=5 | k=10 | k=20 |
|---|---|---|---|
| Naive | 1.000 / 0.726 | 1.000 / 0.789 | 1.000 / 0.849 |
| 하이브리드 | 0.982 / 0.736 | 1.000 / 0.823 | 1.000 / 0.897 |
| 하이브리드+리랭킹 | 1.000 / **0.785** | 1.000 / **0.863** | 1.000 / **0.899** |

- 하이브리드+리랭킹이 두 단위 모두 모든 k에서 Recall이 가장 높다. document Hit는 거의 모두 1.000이라 방식을 구분하지 못하므로 document에서는 Recall로 본다.
- page에서 근거를 하나도 못 찾은 문항은 하이브리드 k=5의 `IS-ADD-01`을 빼면 모두 document에서는 찾아진다. 맞는 문서는 가져오지만 정확한 페이지를 놓치는 경우다(page 기준 미충족 근거 그룹 중 16~21개, 방식·k에 따라 다름).
- 하이브리드는 page k=5에서 Naive보다 낮고(Recall 0.596 < 0.619), document에서는 모든 k에서 Recall이 높다.
- 근거 그룹이 6개 이상인 문항이 6개라 k=5에서는 Recall 만점이 불가능하다. Recall은 k와 함께 해석한다.
- page와 document 점수는 채점 기준이 달라 서로 비교하지 않고, `index_fingerprint`가 다른 결과와도 비교하지 않는다.
- CPU와 GPU에서 문항별 결과가 같았다(page, k=5, 문항 60개 중 다른 문항 0). 다른 기준(document)에서는 확인하지 않았다.

## 테스트

```bash
uv run pytest packages/retrieval
```

- `test_retrieval_mock.py`(목업), `test_dense.py`(Naive), `test_hybrid.py`(BM25, RRF, 하이브리드·리랭킹 연결, 시작 시 오류), `test_reranker.py`(가짜 scorer), `test_evaluator.py`(근거 그룹 채점, 실패·해당 없음, k·동시성 검증, `RETRIEVAL_IMPL` 전환)로 나뉜다.
- 모두 메모리 Qdrant, 가짜 임베더, 가짜 리랭커, 가짜 검색기를 쓰고 실제 모델과 서버는 쓰지 않는다.
- 실제 색인으로 평가하려면 Qdrant와 색인이 필요하다. `unit`은 기본값이 없어 명시한다.

```bash
uv run python -m app.cli eval --k 5 --unit page
```
