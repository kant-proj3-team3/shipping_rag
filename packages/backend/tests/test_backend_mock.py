import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend
from common.errors import IndexNotReadyError, InvalidInputError, RetrievalError
from common.interfaces import AnswerEvaluator, QAService, Retriever, SessionService
from common.types import (
    AnswerEvalRecord,
    AnswerStatus,
    Chunk,
    ErrorCode,
    ExpectedAction,
    GoldenItem,
    IndexManifest,
    QueryRequest,
    RequestContext,
    RetrievalMode,
    RetrievalResult,
    RetrievedChunk,
    ScoreState,
    Split,
)

CTX = RequestContext(request_id="r1")
CHUNK = Chunk(chunk_id="c1", book_id="B1", file_name="B1.pdf", page_start=3, page_end=3, text="본문")


class FakeRetriever:
    supported_modes = list(RetrievalMode)
    index = IndexManifest(
        index_name="t", embedder_id="e", embedding_dim=4, document_count=1, chunk_count=1,
        fingerprint="fp", max_chunk_tokens=8, created_at=datetime.now(UTC),
    )

    def __init__(self, chunks=None, exc=None):
        self.chunks, self.exc = chunks if chunks is not None else [CHUNK], exc

    async def retrieve(self, request, ctx):
        if self.exc:
            raise self.exc
        return RetrievalResult(
            mode=request.mode, k=request.k,
            chunks=[RetrievedChunk(rank=i, score=1.0, chunk=c) for i, c in enumerate(self.chunks, 1)],
        )


def ask(retriever, question="장비 질문입니다", **kw):
    qa = backend.create_qa_service(retriever)
    return asyncio.run(qa.answer(QueryRequest(question=question, **kw), CTX))


def test_protocols():
    r = FakeRetriever()
    assert isinstance(r, Retriever)  # 테스트용 가짜도 현재 Retriever 계약을 만족한다
    assert isinstance(backend.create_qa_service(r), QAService)
    assert isinstance(backend.create_session_service(), SessionService)
    assert isinstance(backend.create_answer_evaluator(None), AnswerEvaluator)


def test_answered_has_code_filled_citations_and_context():
    res = ask(FakeRetriever())
    r = res.response
    assert r.status is AnswerStatus.ANSWERED
    assert (r.citations[0].book_id, r.citations[0].file_name, r.citations[0].page) == ("B1", "B1.pdf", 3)
    assert [c.source_id for c in res.final_context] == ["S1"]
    # 확인되지 않은 값은 0이 아니라 None
    assert r.meta.input_tokens is None and r.meta.cost_usd is None and r.meta.cache_hit is False


def test_empty_retrieval_abstains_without_citations():
    assert ask(FakeRetriever(chunks=[])).response.status is AnswerStatus.ABSTAINED


def test_short_question_needs_clarification():
    assert ask(FakeRetriever(), question="네?").response.status is AnswerStatus.NEEDS_CLARIFICATION


@pytest.mark.parametrize(
    "exc,code",
    [
        (InvalidInputError("x"), ErrorCode.INVALID_INPUT),
        (IndexNotReadyError("x"), ErrorCode.INDEX_NOT_READY),
        (RetrievalError("x"), ErrorCode.RETRIEVAL_FAILED),
        (RuntimeError("x"), ErrorCode.INTERNAL),
    ],
)
def test_exceptions_become_error_responses(exc, code):
    r = ask(FakeRetriever(exc=exc)).response
    assert r.status is AnswerStatus.ERROR and r.error_code is code


def test_session_records_all_but_error():
    sid = "session-abc-0001"
    ask(FakeRetriever(), session_id=sid)
    ask(FakeRetriever(chunks=[]), session_id=sid)
    ask(FakeRetriever(exc=RetrievalError("x")), session_id=sid)  # 오류는 기록하지 않는다
    info = asyncio.run(backend.create_session_service().get(sid, limit=1))
    assert info.turn_count == 2 and len(info.turns) == 1
    assert info.turns[0].status is AnswerStatus.ABSTAINED  # 최근 limit 개
    assert asyncio.run(backend.create_session_service().get("no-such-session", 20)) is None


def test_answer_evaluator_never_invents_scores():
    item = GoldenItem(id="i", split=Split.DEVELOPMENT, question="q", expected_action=ExpectedAction.ANSWER)
    answered, abstained = ask(FakeRetriever()), ask(FakeRetriever(chunks=[]))
    ev = backend.create_answer_evaluator(None)
    out = asyncio.run(ev.evaluate([AnswerEvalRecord(item=item, result=answered), AnswerEvalRecord(item=item, result=abstained)]))
    assert len(out) == 2
    assert out[0].faithfulness.state is ScoreState.UNAVAILABLE and out[0].faithfulness.value is None
    assert out[1].faithfulness.state is ScoreState.NOT_APPLICABLE
    failed = ask(FakeRetriever(exc=RetrievalError("x")))
    err = asyncio.run(ev.evaluate([AnswerEvalRecord(item=item, result=failed)]))
    assert err[0].faithfulness.state is ScoreState.UNAVAILABLE  # 오류 응답은 평균에서 제외


def _client(retriever) -> TestClient:
    manifest = IndexManifest(
        index_name="t", embedder_id="e", embedding_dim=4, document_count=1, chunk_count=1,
        fingerprint="fp", max_chunk_tokens=8, created_at=datetime.now(UTC),
    )
    app = FastAPI()
    app.include_router(
        backend.create_router(backend.create_qa_service(retriever), backend.create_session_service(), manifest)
    )
    return TestClient(app)


def test_http_status_mapping():
    c = _client(FakeRetriever())
    assert c.get("/health").json()["supported_modes"] == ["naive", "hybrid", "hybrid_rerank"]
    ok = c.post("/query", json={"question": "장비 질문입니다", "session_id": "http-session-01"})
    assert ok.status_code == 200 and ok.json()["status"] == "answered"
    assert c.get("/session/http-session-01").json()["turn_count"] == 1
    assert c.get("/session/missing-session-1").status_code == 404
    assert c.post("/query", json={"question": "a" * 501}).status_code == 422
    assert _client(FakeRetriever(exc=InvalidInputError("x"))).post("/query", json={"question": "장비 질문입니다"}).status_code == 400
    assert _client(FakeRetriever(exc=IndexNotReadyError("x"))).post("/query", json={"question": "장비 질문입니다"}).status_code == 503


def test_mock_is_reachable_as_attribute_of_package():
    import backend

    assert backend.mock.__name__ == "backend.mock"
    assert hasattr(backend.mock, "__path__")
