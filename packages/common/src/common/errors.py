"""계약 오류. 모듈은 아래 예외로만 실패를 알린다 (그 외 예외는 INTERNAL로 취급)."""

from __future__ import annotations

from .types import ErrorCode


class ContractError(Exception):
    code: ErrorCode = ErrorCode.INTERNAL

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message


class IndexNotReadyError(ContractError):
    code = ErrorCode.INDEX_NOT_READY


class RetrievalError(ContractError):
    code = ErrorCode.RETRIEVAL_FAILED


class IngestError(ContractError):
    code = ErrorCode.INGEST_FAILED


class InvalidInputError(ContractError):
    """입력이 형식은 맞지만 처리할 수 없다 (예: 질문이 임베딩 입력 한도를 넘는다). 호출 실패(RetrievalError)와 구분한다."""

    code = ErrorCode.INVALID_INPUT
