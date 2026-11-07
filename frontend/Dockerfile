# 프론트엔드 배포용 이미지. Node 로 빌드한 정적 파일을 nginx 가 내려주고, 계약 API 요청은 compose 의 api 로 넘긴다.
# 빌드 컨텍스트는 frontend/ 다. 저장소 루트에서: docker build -t shipping-rag-web frontend

# 1) 빌드: package-lock.json 그대로 설치하고 dist/ 를 만든다
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# 2) 실행: 빌드 결과와 nginx 설정만 올린다 (Node 없이 뜬다)
FROM nginx:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
