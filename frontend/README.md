# 프론트엔드

## 빠르게 실행해 보기

[Docker](https://docs.docker.com/get-docker/)를 설치하고 저장소 루트에서 시작합니다.

### 1. 백엔드(api) 실행

```bash
docker compose up -d --build api
docker compose --profile tools run --rm cli index
docker compose restart api
```

`api`와 `qdrant` · `redis`를 띄우고 목업 색인을 만든 뒤, `api`가 색인을 읽도록 다시 시작합니다. 전에 색인한 적이 있으면 둘째 줄에서 `이미 있는 인덱스다` 오류가 나는데, 색인이 이미 있다는 뜻이라 그대로 진행하면 됩니다.

### 2. 프론트 빌드 · 실행

```bash
docker compose -f frontend/docker-compose.yml up -d --build
```

화면을 내려주는 `web`(nginx)과 화면 로그를 저장하는 `log-server`(Node.js + winston)를 띄웁니다. `web`은 API 요청을 `api` 컨테이너로, 화면 로그를 `log-server`로 넘깁니다. 3000 포트를 다른 프로그램이 쓰고 있으면 환경 변수 `WEB_PORT`로 바꿉니다(예: `WEB_PORT=3001`). 전에 `docker run`으로 띄운 `shipping-rag-web` 컨테이너가 있으면 포트가 겹치니 `docker rm -f shipping-rag-web`으로 먼저 지웁니다.

### 3. 확인

<http://localhost:3000>을 열어 왼쪽 아래 서버 상태가 "서버 정상"이면 준비 완료입니다.

## 화면 로그

화면에서 난 경고와 오류를 `log-server`가 받아 `frontend/logs/`에 날짜별 텍스트 파일로 저장합니다. 메모장이나 편집기로 바로 열 수 있고, 컨테이너를 지워도 남습니다. 배포 이미지에서만 보내고, `npm run dev`로 띄운 개발 서버는 브라우저 콘솔에만 남깁니다.

```text
2026-11-09 15:17:06,312 WARN  [browser] 질문 요청이 실패했다 issue=407671 error=RequestError code=network cause="서버에 연결하지 못했습니다" ua="Mozilla/5.0 ..."
2026-11-09 15:17:14,502 ERROR [browser] 잡히지 않은 오류가 났다 issue=1d6dd4 error=TypeError cause="e is not a function" ua="Mozilla/5.0 ..."
    TypeError: e is not a function
        at t (src/components/ChatView.tsx:42:7)
```

| 항목      | 내용                                                                   |
| --------- | ---------------------------------------------------------------------- |
| `WARN`    | 요청 실패, 서버의 `status=error` 응답, 브라우저 저장 실패              |
| `ERROR`   | 화면을 그리다 난 오류, 아무도 잡지 않은 예외                           |
| `issue`   | 같은 오류에 붙는 같은 값. 검색해 횟수를 세거나 GitHub 이슈에 적어 추적 |
| `request` | 서버 오류 응답의 `request_id`. 백엔드 기록과 맞춰 볼 때 사용           |

같은 오류가 몇 번 났는지는 아래처럼 셉니다. 파일마다 건수가 나옵니다.

```bash
grep -c "issue=407671" frontend/logs/client-2026-11-09*
```

PowerShell에서는 다음과 같습니다.

```powershell
(Select-String -Path frontend/logs/client-2026-11-09* -Pattern "issue=407671").Count
```

같은 오류가 5초 안에 되풀이되면 한 번만 보내므로, 이 건수는 실제 발생 횟수보다 적을 수 있습니다.

파일이 10MB를 넘으면 `client-2026-11-09.log.1`처럼 번호를 붙여 이어 쓰며, 번호가 클수록 최신입니다. 날짜별 로그는 하루 20MB까지 쌓고 14일이 지나면 지웁니다.

하루 20MB를 넘으면 로그를 버리지 않고 `client-2026-11-09-overflow.log`에 이어 씁니다. 넘침 파일은 최근 10개(100MB)만 유지하고 오래된 것부터 지우므로, 요청이 몰려도 날짜별 로그는 밀려나지 않습니다. 한도는 `log-server`를 다시 시작하면 처음부터 다시 셉니다.

`ERROR`의 스택은 소스맵으로 원본 파일 위치로 바꿔 남깁니다. 소스맵은 `log-server` 이미지에만 있고 화면으로 공개되지 않습니다.

질문 · 답변 · 세션 id는 보내지 않습니다. 입구가 인증 없이 열려 있어 누구나 로그를 보낼 수 있으니, 디버깅 자료로만 씁니다. `log-server`가 꺼져 있어도 화면은 그대로 동작하고, 그동안의 로그만 남지 않습니다.

Linux에서 `frontend/logs/` 소유자의 uid가 1000이 아니면 `LOG_UID=$(id -u)`를 붙여 실행합니다. 파일을 쓸 수 없으면 `log-server`는 멈추지 않고 콘솔(`docker compose -f frontend/docker-compose.yml logs log-server`)에만 남기면서 원인을 출력합니다.

`/client-logs`는 프론트엔드 안의 약속이라 `contracts/openapi.json`에 없습니다. 형식은 `shared/clientLog.ts`에 있고, 보내는 쪽은 `src/lib/logger.ts`, 받는 쪽은 `server/src/app.ts`입니다.

## API 타입 다시 만들기

`contracts/openapi.json`이 바뀌면 화면 코드가 쓰는 타입과 응답 검증 스키마를 다시 만듭니다. [Node.js](https://nodejs.org/)를 설치하고 `frontend` 폴더에서 실행합니다.

```bash
npm ci
npm run gen:api
```

`openapi-typescript`가 `src/api/generated/openapi.d.ts`(서버 형식 TS 타입)를 만들고, 이어서 `scripts/gen-schemas.mjs`가 `src/api/generated/schemas.generated.ts`(zod 스키마 · 화면 타입 · 변환 함수)를 만듭니다.

```bash
npm run check:api
npm run typecheck
```

`check:api`는 생성 파일이 지금의 `openapi.json`과 같은지만 보고, 다르면 오류로 끝납니다. `typecheck`는 화면 코드가 바뀐 타입에 맞는지 확인합니다.

`gen:api`가 `gen-schemas: schema-descriptions.mjs: 없는 필드 "HealthResponse.index_ready"`처럼 멈추면 계약에서 그 필드가 빠졌거나 설명이 생긴 것이니 `scripts/schema-descriptions.mjs`에서 그 항목을 지웁니다. 그 밖의 오류는 생성 스크립트가 다루지 않는 스키마 형식이라 `scripts/gen-schemas.mjs`를 고쳐야 합니다.
