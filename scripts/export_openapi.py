"""계약 타입에서 OpenAPI를 뽑는다. 프론트엔드 타입 생성과 CI의 diff 검사에 쓴다.

실행:  uv run python scripts/export_openapi.py
이 앱은 라우트 껍데기일 뿐 로직이 없다. 실제 서버는 backend 모듈이 같은 모델로 구현한다.
"""

import json
from pathlib import Path

from fastapi import FastAPI, Path as PathParam, Query

from common.api import (
    ERROR_HTTP_STATUS,
    HTTP_SESSION_NOT_FOUND,
    PATH_HEALTH,
    PATH_QUERY,
    PATH_SESSION,
    SESSION_DEFAULT_LIMIT,
    SESSION_MAX_LIMIT,
)
from common.types import (
    SESSION_ID_PATTERN,
    ApiError,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    SessionInfo,
)

app = FastAPI(title="RAG Q&A API", version="0.1.0")

_error_responses = {
    code: {"model": QueryResponse, "description": "status=error"}
    for code in sorted(set(ERROR_HTTP_STATUS.values()))
}


@app.get(PATH_HEALTH, response_model=HealthResponse)
def health() -> HealthResponse: ...


@app.post(PATH_QUERY, response_model=QueryResponse, responses=_error_responses)
def query(body: QueryRequest) -> QueryResponse: ...


@app.get(
    PATH_SESSION,
    response_model=SessionInfo,
    responses={HTTP_SESSION_NOT_FOUND: {"model": ApiError, "description": "session_not_found"}},
)
def session(
    session_id: str = PathParam(pattern=SESSION_ID_PATTERN),
    limit: int = Query(SESSION_DEFAULT_LIMIT, ge=1, le=SESSION_MAX_LIMIT),
) -> SessionInfo: ...


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, help="기본값은 contracts/openapi.json (build_contract_manifest --check 가 임시 경로로 재생성해 비교한다)")
    out = ap.parse_args().out or Path(__file__).resolve().parents[1] / "contracts" / "openapi.json"
    out.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
