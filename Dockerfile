# api·cli 공용 이미지. uv workspace 전체(app/ + packages/*)를 한 환경에 설치한다.
# 전제: 루트 pyproject.toml, uv.lock, 각 packages/*/pyproject.toml 이 있어야 한다 (uv lock 으로 생성).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 1) 의존성 레이어: 선언 파일만 먼저 복사해 소스가 바뀌어도 설치 캐시를 재사용한다
COPY pyproject.toml uv.lock ./
COPY packages/common/pyproject.toml packages/common/pyproject.toml
COPY packages/chunking/pyproject.toml packages/chunking/pyproject.toml
COPY packages/retrieval/pyproject.toml packages/retrieval/pyproject.toml
COPY packages/backend/pyproject.toml packages/backend/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace

# 2) 소스 복사 후 workspace 멤버 설치
COPY app ./app
COPY packages ./packages
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# 컨테이너는 root가 아닌 사용자로 실행한다
# /mock_index: 목업 인덱서의 manifest 저장 위치 (api·cli 가 볼륨으로 공유. 실제 Qdrant 구현에서는 쓰지 않는다)
RUN useradd --create-home appuser && mkdir -p /models /mock_index && chown -R appuser /models /mock_index /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
