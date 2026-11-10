"""HTTP 계약 상수. 프론트엔드와 백엔드가 공유하는 유일한 약속 (OpenAPI의 원본)."""

from __future__ import annotations

from .types import ErrorCode

PATH_HEALTH = "/health"
PATH_QUERY = "/query"
PATH_SESSION = "/session/{session_id}"  # GET. 쿼리 파라미터 limit (최근 turn 개수)
SESSION_DEFAULT_LIMIT = 20
SESSION_MAX_LIMIT = 100
HTTP_SESSION_NOT_FOUND = 404  # 한 번도 기록되지 않은 세션(세션은 만료되지 않는다). 본문은 ApiError

# 입력 검증 실패는 FastAPI 기본 422. 처리 실패(status=error)는 아래 상태로, 본문은 QueryResponse.
# 정상 처리된 answered / needs_clarification / abstained 는 모두 200.
ERROR_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_INPUT: 400,  # 스키마 검증 실패(422)와 구분한다
    ErrorCode.INDEX_NOT_READY: 503,
    ErrorCode.RETRIEVAL_FAILED: 502,
    ErrorCode.MODEL_TIMEOUT: 504,
    ErrorCode.MODEL_FAILED: 502,
    ErrorCode.OUTPUT_INVALID: 502,
    ErrorCode.INTERNAL: 500,
}
