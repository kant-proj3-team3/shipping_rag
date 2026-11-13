# 검색 평가 결과: k=5, unit=page

세 검색 방식(naive / hybrid / hybrid_rerank)을 같은 인덱스·같은 질문·같은 k로 평가했다. 원본 수치는 같은 폴더의 JSON(`RetrievalReport`를 그대로 직렬화)에 있다.

- `eval_k5_page.json`: CPU 실행
- `eval_k5_page_gpu.json`: GPU 실행

## 실행 조건

| 항목 | 값 |
|---|---|
| 실행일 | 2026-11-11 |
| k / unit | 5 / page |
| 인덱스 | `rag-dev-chanyeongg3` (문서 50, 청크 15,053) |
| `index_fingerprint` | `0acd52b3e8804b0d6e07c54dfa396f2d8b01a05402f912b1ceeeca481edbe2f4` |
| `golden_fingerprint` | `6fb91800a14772fdf63c158d760323b6864d8979f8f9ec1f7fbf3210cb7b1bef` |
| 임베더 | `intfloat/multilingual-e5-base` (`prefix=e5, norm=l2, max=512, dim=768`) |
| 리랭커 | `BAAI/bge-reranker-v2-m3`, 입력 한도 512 |
| 문항 | 60 (채점 56, 근거 그룹 없음 4, 검색 실패 0) |
| 실행 방식 | `app.cli eval`과 같은 조립(`build_base`·`build_services`)으로 `evaluate()`를 호출 |

## 결과

| 방식 | Hit@5 | Recall@5 | 채점 | n/a | 실패 |
|---|---|---|---|---|---|
| naive | 0.911 | 0.619 | 56 | 4 | 0 |
| hybrid | 0.875 | 0.596 | 56 | 4 | 0 |
| hybrid_rerank | **0.964** | **0.676** | 56 | 4 | 0 |

평균은 채점된 56문항만으로 계산했다. 근거 그룹이 없는 문항(`IS-DEV-12`, `IS-DEV-30`, `IS-ADD-12`, `IS-ADD-29`)은 `not_applicable`로 평균에서 제외했다.

## 해석할 때 주의

- **Recall 상한**: 근거 그룹이 6개 이상인 문항이 6개(최대 7개)다. k=5에서는 이 문항들의 Recall 만점이 사실상 어렵다. Recall은 k와 함께 읽는다.
- **hybrid < naive**: BM25를 결합한 hybrid가 naive보다 Hit·Recall 모두 낮다. 원인은 이번 실행에서 분석하지 않았다.
- **hybrid_rerank에서도 Hit=0인 문항**: `IS-ADD-06`, `IS-ADD-10`.
- 점수는 같은 인덱스·같은 골든 데이터셋 안에서만 비교한다. fingerprint가 다른 결과와 비교하지 않는다.

## CPU와 GPU 비교

같은 조건으로 CPU와 GPU에서 각각 실행했다.

| 방식 | 문항별 결과 차이 | CPU 시간 | GPU 시간 |
|---|---|---|---|
| naive | 0 / 60 | 1.6초 | 1.6초 |
| hybrid | 0 / 60 | 8.4초 | 10.4초 |
| hybrid_rerank | 0 / 60 | 798.5초 | 118.6초 |

- 세 방식 모두 60문항의 Hit·Recall·`satisfied_groups`가 CPU와 GPU에서 완전히 같았다. 이번 조건에서는 실행 기기가 점수에 영향을 주지 않았다.
- 환경: CPU는 torch 2.15.0+cpu(저장소 환경), GPU는 torch 2.14.1+cu130(별도 환경, RTX 5060 Laptop).
- 두 실행이 같은 시간대에 동시에 돌았으므로 걸린 시간은 서로 영향을 받았을 수 있다. 시간은 대략적인 비교로만 본다. JSON의 `device`는 실행 환경에서 CUDA를 쓸 수 있었는지를 기록한 값이다.
