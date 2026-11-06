"""목업 QA 서비스: LLM 없이 계약만 지킨다. 검색 → 문맥 → 고정 형식 답변.

실제 구현이 지킬 규칙을 같이 보여준다: 예외는 status=error 로 변환, 빈 검색은 모델 호출 없이 abstained,
문서명·페이지는 Chunk 에서 코드가 채운다, answered/needs_clarification/abstained 만 세션에 기록한다.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from common.errors import ContractError, IndexNotReadyError, InvalidInputError, RetrievalError
from common.interfaces import Retriever
from common.types import (
    AnswerStatus,
    Citation,
    ContextItem,
    ErrorCode,
    QAResult,
    QueryMeta,
    QueryRequest,
    QueryResponse,
    RequestContext,
    RetrievalMode,
    RetrievalRequest,
    SessionTurn,
)

from .session import InMemorySessionStore

DEFAULT_MODE = RetrievalMode.HYBRID
DEFAULT_K = 5
_MIN_QUESTION_LEN = 4  # 목업의 되묻기 트리거: 너무 짧은 질문

_USER_MESSAGES = {
    ErrorCode.INVALID_INPUT: "질문을 처리할 수 없습니다. 더 짧게 다시 질문해 주세요.",
    ErrorCode.INDEX_NOT_READY: "검색 인덱스가 아직 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.",
    ErrorCode.RETRIEVAL_FAILED: "자료를 검색하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    ErrorCode.INTERNAL: "내부 오류가 발생했습니다.",
}


class MockQAService:
    def __init__(self, retriever: Retriever, store: InMemorySessionStore) -> None:
        self._retriever = retriever
        self._store = store

    async def answer(self, request: QueryRequest, ctx: RequestContext) -> QAResult:
        started = time.perf_counter()
        mode = request.retrieval_mode or DEFAULT_MODE

        def meta() -> QueryMeta:
            # 토큰·비용·trace_id 는 확인된 값이 없어 None 이다 (0으로 채우지 않는다)
            return QueryMeta(retrieval_mode=mode, latency_ms=(time.perf_counter() - started) * 1000)

        def error(code: ErrorCode) -> QAResult:
            resp = QueryResponse(
                request_id=ctx.request_id,
                status=AnswerStatus.ERROR,
                answer=_USER_MESSAGES[code],
                reason="서버 오류",
                error_code=code,
                meta=meta(),
            )
            return QAResult(response=resp)  # 오류는 세션에 기록하지 않는다

        if len(request.question.strip()) < _MIN_QUESTION_LEN:
            return self._finish(
                request, ctx, mode, meta(), AnswerStatus.NEEDS_CLARIFICATION,
                "질문이 너무 짧습니다. 어떤 자료의 무엇이 궁금한지 구체적으로 알려주세요.",
                "질문만으로는 근거를 찾을 수 없다", [],
            )

        try:
            result = await self._retriever.retrieve(
                RetrievalRequest(query=request.question, mode=mode, k=DEFAULT_K), ctx
            )
        except InvalidInputError:
            return error(ErrorCode.INVALID_INPUT)
        except IndexNotReadyError:
            return error(ErrorCode.INDEX_NOT_READY)
        except (RetrievalError, ContractError):
            return error(ErrorCode.RETRIEVAL_FAILED)
        except Exception:
            return error(ErrorCode.INTERNAL)

        context = [ContextItem(source_id=f"S{i}", chunk=rc.chunk) for i, rc in enumerate(result.chunks, start=1)]
        if not context:  # 빈 문맥이면 모델을 호출하지 않는다
            return self._finish(
                request, ctx, mode, meta(), AnswerStatus.ABSTAINED,
                "제공된 자료에서 답할 근거를 찾지 못했습니다. 관련 문서를 추가로 확인해 주세요.",
                "검색 결과가 없다", [],
            )

        top = context[0]
        citations = [
            Citation(source_id=top.source_id, book_id=top.chunk.book_id, file_name=top.chunk.file_name, page=top.chunk.page_start)
        ]
        return self._finish(
            request, ctx, mode, meta(), AnswerStatus.ANSWERED,
            f"[목업 답변] {top.chunk.text}", "가장 관련 높은 검색 결과를 그대로 보여준다 (LLM 미사용)",
            citations, context,
        )

    def _finish(
        self,
        request: QueryRequest,
        ctx: RequestContext,
        mode: RetrievalMode,
        meta: QueryMeta,
        status: AnswerStatus,
        answer: str,
        reason: str,
        citations: list[Citation],
        context: list[ContextItem] | None = None,
    ) -> QAResult:
        resp = QueryResponse(
            request_id=ctx.request_id, status=status, answer=answer, reason=reason, citations=citations, meta=meta
        )
        if request.session_id:
            self._store.append(
                request.session_id,
                SessionTurn(
                    request_id=ctx.request_id,
                    asked_at=datetime.now(UTC),
                    question=request.question,
                    retrieval_mode=mode,
                    status=status,
                    answer=answer,
                    citations=citations,
                ),
            )
        return QAResult(response=resp, final_context=context or [])
