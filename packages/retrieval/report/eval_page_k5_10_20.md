# 검색 평가 결과: k=5·10·20, unit=page

세 검색 방식(naive / hybrid / hybrid_rerank)을 같은 인덱스·같은 질문으로 k만 바꿔 평가했다. 원본 수치는 같은 폴더의 JSON(`RetrievalReport`를 그대로 직렬화)에 있다.

- `eval_k5_page_gpu.json`, `eval_k10_page_gpu.json`, `eval_k20_page_gpu.json`
- k=5의 CPU 실행과 CPU·GPU 비교는 `eval_k5_page.md` 참고(문항별 결과 차이 0건)

## 실행 조건

| 항목 | 값 |
|---|---|
| 실행일 | 2026-11-11 |
| unit | page |
| k | 5, 10, 20 |
| 인덱스 | `rag-dev-chanyeongg3` (문서 50, 청크 15,053) |
| `index_fingerprint` | `0acd52b3e8804b0d6e07c54dfa396f2d8b01a05402f912b1ceeeca481edbe2f4` |
| `golden_fingerprint` | `6fb91800a14772fdf63c158d760323b6864d8979f8f9ec1f7fbf3210cb7b1bef` |
| 임베더 | `intfloat/multilingual-e5-base` (`prefix=e5, norm=l2, max=512, dim=768`) |
| 리랭커 | `BAAI/bge-reranker-v2-m3`, 입력 한도 512, 후보 50개(`CANDIDATE_POOL`) |
| 문항 | 60 (채점 56, 근거 그룹 없음 4, 검색 실패 0). 모든 k에서 같음 |
| 실행 환경 | GPU (torch 2.14.1+cu130, RTX 5060 Laptop) |
| 실행 방식 | `app.cli eval`과 같은 조립(`build_base`·`build_services`)으로 `evaluate()`를 호출 |

세 실행 모두 `index_fingerprint`와 `golden_fingerprint`가 같다.

## 결과

### Hit@k

| 방식 | k=5 | k=10 | k=20 |
|---|---|---|---|
| naive | 0.911 | 0.982 | 0.982 |
| hybrid | 0.875 | 0.946 | 0.982 |
| hybrid_rerank | **0.964** | **0.982** | **0.982** |

### Recall@k

| 방식 | k=5 | k=10 | k=20 |
|---|---|---|---|
| naive | 0.619 | 0.689 | 0.733 |
| hybrid | 0.596 | 0.700 | 0.794 |
| hybrid_rerank | **0.676** | **0.765** | **0.808** |

### Recall 만점(1.0) 문항 수 (채점 56문항 중)

| 방식 | k=5 | k=10 | k=20 |
|---|---|---|---|
| naive | 17 | 21 | 22 |
| hybrid | 15 | 21 | 29 |
| hybrid_rerank | 20 | 27 | 32 |

평균은 채점된 56문항만으로 계산했다. 근거 그룹이 없는 `IS-DEV-12`, `IS-DEV-30`, `IS-ADD-12`, `IS-ADD-29`는 `not_applicable`로 제외했다.

## 관찰

- **hybrid_rerank가 모든 k에서 Hit·Recall 모두 가장 높다.** 격차는 k가 작을수록 크다. Recall 기준으로 naive 대비 k=5에서 +0.057, k=10에서 +0.076, k=20에서 +0.075다.
- **hybrid는 k=5에서 naive보다 낮지만 k가 커지면 앞선다.** Recall은 k=10에서 naive를 넘고, k=20에서는 차이가 +0.061이다. BM25가 근거를 후보에 넣기는 하지만 상위 순위로 올리지는 못하는 것으로 보인다. 원인은 이번 실행에서 분석하지 않았다.
- **Hit은 k=10부터 거의 포화된다.** naive와 hybrid_rerank는 k=10에서 이미 0.982(56문항 중 55문항)다.
- **k=20에서도 Hit=0인 문항: `IS-ADD-10`** (세 방식 공통). 순위 문제가 아니라 근거 청크가 후보에 들어오지 않는 문항이다. 따로 확인이 필요하다.
- k를 늘리면 찾아진 문항:

  | 방식 | k=5에서 Hit=0 | k=10에서 Hit=0 | k=20에서 Hit=0 |
  |---|---|---|---|
  | naive | ADD-07, 09, 10, 13, 16 | ADD-10 | ADD-10 |
  | hybrid | ADD-01, 02, 03, 07, 10, 13, 21 | ADD-03, 07, 10 | ADD-10 |
  | hybrid_rerank | ADD-06, 10 | ADD-10 | ADD-10 |

## 근거 그룹 수별 Recall (hybrid_rerank)

| 근거 그룹 수 | 문항 수 | k=5 | k=10 | k=20 |
|---|---|---|---|---|
| 1 | 8 | 0.875 | 0.875 | 0.875 |
| 2~5 | 42 | 0.675 | 0.768 | 0.819 |
| 6~7 | 6 | 0.417 | 0.595 | 0.643 |

- 그룹이 1개인 문항은 k와 상관없이 같다. 8문항 중 1문항(`IS-ADD-10`)을 끝까지 못 찾는다.
- 그룹이 6~7개인 문항은 k=5에서 구조적으로 불리하다(결과 5개로 그룹 6~7개를 채워야 함). k=10에서 크게 오른다.

## 해석할 때 주의

- 점수는 같은 인덱스·같은 골든 데이터셋 안에서만 비교한다. fingerprint가 다른 결과와 비교하지 않는다.
- 리랭커 후보는 k와 상관없이 50개다. k가 50에 가까워지면 hybrid와 hybrid_rerank의 결과 집합이 같아진다. 리랭킹의 효과는 작은 k에서 본다.
- 검색 결과 k개는 답변 프롬프트에 그대로 들어가므로, 평가에서 큰 k가 좋다고 해서 서비스에 그대로 쓸 수는 없다(토큰·비용·잡음 증가).
- 걸린 시간(JSON의 `elapsed_seconds`)은 참고용이다. hybrid_rerank는 k와 상관없이 60문항에 약 110초가 걸렸다.
