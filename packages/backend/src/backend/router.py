"""FastAPI 라우터. 경로·모델·HTTP 상태는 common.api 와 contracts/openapi.json 을 그대로 따른다."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse

from common.api import (
    ERROR_HTTP_STATUS,
    HTTP_SESSION_NOT_FOUND,
    PATH_HEALTH,
    PATH_QUERY,
    PATH_SESSION,
    SESSION_DEFAULT_LIMIT,
    SESSION_MAX_LIMIT,
)
from common.interfaces import QAService, SessionService
from common.types import (
    SESSION_ID_PATTERN,
    AnswerStatus,
    ApiError,
    ErrorCode,
    HealthResponse,
    IndexManifest,
    QueryRequest,
    QueryResponse,
    RequestContext,
    RetrievalMode,
    SessionInfo,
)

_error_responses = {
    code: {"model": QueryResponse, "description": "status=error"}
    for code in sorted(set(ERROR_HTTP_STATUS.values()))
}


def build_router(qa_service: QAService, session_service: SessionService, index: IndexManifest) -> APIRouter:
    router = APIRouter()

    @router.get(PATH_HEALTH, response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            index_ready=True,
            index_name=index.index_name,
            embedder_id=index.embedder_id,
            supported_modes=list(RetrievalMode),
        )

    @router.post(PATH_QUERY, response_model=QueryResponse, responses=_error_responses)
    async def query(body: QueryRequest):
        ctx = RequestContext(request_id=uuid.uuid4().hex)
        response = (await qa_service.answer(body, ctx)).response  # final_context 는 평가용이라 내보내지 않는다
        if response.status is AnswerStatus.ERROR:
            code = response.error_code or ErrorCode.INTERNAL
            return JSONResponse(
                status_code=ERROR_HTTP_STATUS.get(code, 500), content=response.model_dump(mode="json")
            )
        return response

    @router.get(
        PATH_SESSION,
        response_model=SessionInfo,
        responses={HTTP_SESSION_NOT_FOUND: {"model": ApiError, "description": "session_not_found"}},
    )
    async def session(
        session_id: str = Path(pattern=SESSION_ID_PATTERN),
        limit: int = Query(SESSION_DEFAULT_LIMIT, ge=1, le=SESSION_MAX_LIMIT),
    ):
        info = await session_service.get(session_id, limit)
        if info is None:
            err = ApiError(error_code=ErrorCode.SESSION_NOT_FOUND, message="세션을 찾을 수 없습니다.")  # 세션은 만료되지 않는다(계약 v0.1.1). 한 번도 기록되지 않은 세션뿐이다
            return JSONResponse(status_code=HTTP_SESSION_NOT_FOUND, content=err.model_dump(mode="json"))
        return info

    return router
