# BM25 토큰화 비교 기준선

BM25 토큰화를 바꾸기 전의 평가 결과다. 토큰화 변형은 이 폴더와 비교한다.

| 파일 | 내용 |
|---|---|
| `eval_k5_page_gpu.json`, `eval_k10_page_gpu.json`, `eval_k20_page_gpu.json` | 세 방식의 `RetrievalReport` (unit=page, GPU) |
| `bm25_ranks.json` | 문항별·근거 그룹별 BM25 단독 최고 순위와 Dense(top50) 최고 순위, 방식별 찾은 그룹 수 |

## 기준선 조건

| 항목 | 값 |
|---|---|
| 실행일 | 2026-11-11 |
| 코드 | `feat/retrieval` HEAD `a85d74f` + 커밋 전 변경(`packages/retrieval/src` 5개 파일, diff sha256 앞 16자 `a9105611c03992d9`) |
| 토큰화 | `re.findall(r"\w+(?:-\w+)*", text.lower())`. 띄어쓰기 단위, 조사가 붙은 채로 비교, 하이픈 식별자는 한 단어 |
| 인덱스 | `rag-dev-chanyeongg3`, `index_fingerprint` `0acd52b3e8804b0d6e07c54dfa396f2d8b01a05402f912b1ceeeca481edbe2f4` |
| 골든 | `golden_fingerprint` `6fb91800a14772fdf63c158d760323b6864d8979f8f9ec1f7fbf3210cb7b1bef` (채점 56문항: DEV 28, ADD 28) |
| 환경 | GPU, torch 2.14.1+cu130 |

## 기준선 요약 (BM25 단독)

- 근거 그룹 178개 중 BM25 50위 안: 133개 (DEV 63/86, ADD 70/92)
- 근거 그룹별 최고 순위의 중앙값: 7위
