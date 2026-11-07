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
docker build -t shipping-rag-web frontend
docker run -d --name shipping-rag-web --network rag-qa_default -p 3000:80 shipping-rag-web
```

빌드한 화면을 nginx가 내려주고, API 요청은 `api` 컨테이너로 넘깁니다. 3000 포트를 다른 프로그램이 쓰고 있으면 `-p 3001:80`처럼 앞 숫자를 바꿉니다.

### 3. 확인

<http://localhost:3000>을 열어 왼쪽 아래 서버 상태가 "서버 정상"이면 준비 완료입니다.

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
