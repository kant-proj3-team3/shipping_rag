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
