# frontend — React 클라이언트

## 범위

질문 입력, 검색 방식 선택, 응답 상태별 화면, 세션 이력 복원. 파이썬 패키지가 아니라 `frontend/`에 둔다.

## 소비하는 계약

- `contracts/openapi.json`(`/health`, `/query`, `/session/{session_id}`)이 유일한 약속이다. **TS 타입은 이 파일에서 생성**하고 손으로 따로 쓰지 않는다.
- 개발 중 화면은 아래의 **목업 api**(서버 목업)로 확인한다. 클라이언트 쪽에 따로 목업을 두지 않는다(목업을 두 벌 관리하지 않는다).
- 서버 목업이 만들지 못하는 상태(`status=error` 등)는 `contracts/examples/*.json`을 돌려주는 가짜 클라이언트로 테스트에서 확인한다.
- 실제 HTTP 계약으로 응답하는 **목업 api**도 띄울 수 있다: `docker compose up -d --build api`(또는 `MOCK_INDEX_READY=1 uv run uvicorn app.api:create_app --factory`) 후 `http://localhost:8000`(`/docs`에서 확인). 응답 내용은 목업이라 의미가 없고 형식만 계약과 같다. 색인을 거치려면 `docker compose --profile tools run --rm cli index` 후 api 를 재시작한다.
- 브라우저에서 api 를 직접 부르려면 api 환경의 `CORS_ALLOW_ORIGINS`에 개발 서버 주소(예: `http://localhost:5173`, 쉼표로 여러 개)를 적는다(`.env`에 적어도 된다). 기본값은 비어 있어 CORS 를 켜지 않는다. 적지 않은 출처는 허용하지 않고, 허용 메서드는 GET·POST, 헤더는 Content-Type 이다. 개발 서버 프록시(예: Vite `server.proxy`)를 쓰면 설정이 필요 없다.

## 화면 책임

| status | 화면 |
|---|---|
| `answered` | 답변 + 출처(문서명·페이지) |
| `needs_clarification` | 되묻는 문장 + 보완 질문 입력 (대화 메모리가 없어도 완성된 질문을 새로 보내면 된다) |
| `abstained` | 보류 이유 + 필요한 자료 설명. 오류처럼 보이지 않게 구분 |
| `error` | 사용자용 오류 문구. `error_code`는 로그용 |

- 상태 판단, 출처 매핑, 점수 계산은 하지 않는다. 서버가 준 값을 보여준다.
- `source_id`(S1…)는 요청 안에서만 유효하다. 화면에는 `citations`의 문서명·페이지를 보여주고 `source_id`는 노출하지 않는다.
- `/health`의 `supported_modes`로 검색 방식 선택지를 만든다.
- 세션: 첫 질문 전에 UUID를 만들어 `session_id`로 보낸다. 새로고침 후 `GET /session/{id}`로 이력을 복원하고, 404면 새 세션을 시작한다.
- 오류 처리: 422(스키마 검증), 400(`invalid_input`, 예: 질문이 너무 김), 5xx(`status=error` 본문). 질문은 최대 500자라 입력 단계에서 막는다.
- 개발자용으로 `meta`(지연·토큰·비용·`cache_hit`)를 보여줄 수 있다. 모르는 값은 `null`이니 0으로 표시하지 않는다.

## 확인

OpenAPI가 바뀌면 타입을 다시 생성하고 빌드·타입 검사를 통과시킨다. 완료 전 서버 목업 api로 화면을 확인하고, 서버 목업이 만들지 못하는 상태는 테스트로 확인한다.
