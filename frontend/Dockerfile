# 프론트엔드 배포용 이미지 두 가지. 실행은 docker-compose.yml 이 하고, 빌드 컨텍스트는 frontend/ 다.
# - web: Node 로 빌드한 정적 파일을 nginx 가 내려주고, 계약 API 요청은 compose 의 api 로, 화면 로그는 log-server 로 넘긴다
# - log-server: 화면 로그를 받아 winston 으로 파일에 남긴다

# 1) 빌드: package-lock.json 그대로 설치하고 dist/ 를 만든다 (워크스페이스라 server/package.json 도 있어야 설치된다).
#    소스맵은 공개하지 않도록 dist/ 밖으로 옮긴다
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY server/package.json server/
RUN npm ci
COPY . .
RUN npm run build && mkdir sourcemaps && mv dist/assets/*.map sourcemaps/

# 2) 로그 서버: 서버 의존성과 소스, 스택을 원본 위치로 바꿀 소스맵만 올린다. Node 가 TypeScript 를 그대로 실행한다
FROM node:24-alpine AS log-server
ENV NODE_ENV=production
ENV LOG_DIR=/var/log/shipping-rag
ENV SOURCE_MAP_DIR=/app/sourcemaps
WORKDIR /app
COPY package.json package-lock.json ./
COPY server/package.json server/
RUN npm ci --omit=dev --workspace=server
COPY server/src server/src
COPY shared shared
COPY --from=build /app/sourcemaps sourcemaps
# root 가 아닌 사용자로 실행해도 로그를 쓸 수 있게 폴더 소유자를 맞춘다
RUN mkdir -p "$LOG_DIR" && chown node:node "$LOG_DIR"
USER node
EXPOSE 3001
CMD ["node", "server/src/main.ts"]

# 3) 화면: 빌드 결과와 nginx 설정만 올린다 (Node 없이 뜬다). 마지막 단계라 target 없는 docker build 의 결과물이다
FROM nginx:1.29-alpine AS web
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
