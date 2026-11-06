## 변경 요약
<!-- 무엇을 왜 바꿨는지 2~3줄. -->

## 대상 모듈
- [ ] common / contracts (계약)
- [ ] chunking
- [ ] retrieval
- [ ] backend
- [ ] frontend
- [ ] app
- [ ] 인프라 · 문서 · CI

## 계약 영향
<!--
없으면 "없음"이라고 쓴다.
있으면: CONTRACT_VERSION 변경(x.y.z → x.y.z), CHANGELOG 항목, 영향받는 모듈 담당자를 @멘션한다.
CODEOWNERS 는 소유자 중 한 명의 승인만 요구하므로, 영향받는 담당자는 직접 리뷰어로 지정한다.
-->

## 실행한 검사
- [ ] `python scripts/build_contract_manifest.py --check`
- [ ] 모듈 테스트 `pytest packages/<모듈>`
- [ ] (계약 변경 시) `python scripts/check_dataset_mapping.py`
- [ ] (경계 확인) `python scripts/import_lint.py`
<!-- 실행하지 못한 검사가 있으면 아래에 이유를 적는다. 검사가 필요 없는 PR이면 "해당 없음"과 이유를 쓴다. -->

## 검토자가 볼 곳
<!-- 중점 확인 파일, 판단이 필요한 결정, 알려진 한계. -->

## 에이전트 사용
- [ ] Claude Code 등 에이전트가 코드를 작성했다 (작성자가 diff 를 모두 읽었다)
