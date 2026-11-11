import asyncio
from datetime import UTC, datetime

import pytest

import retrieval
from common.errors import IndexNotReadyError, InvalidInputError
from common.interfaces import RetrievalEvaluator, Retriever
from common.types import (
    EvidenceRef,
    EvidenceUnit,
    ExpectedAction,
    GoldenItem,
    IndexManifest,
    RequestContext,
    RetrievalMode,
    RetrievalRequest,
    ScoreState,
    Split,
)
from retrieval.mock.retriever import DEMO_CHUNKS


class FakeEmbedder:
    embedder_id = "fake"
    dimension = 4
    max_input_tokens = 10

    def count_tokens(self, text):
        return len(text.split())

    def embed_passages(self, texts):
        return [[0.0] * 4 for _ in texts]

    def embed_query(self, text):
        if len(text.split()) > self.max_input_tokens:
            raise InvalidInputError("too long")
        return [0.0] * 4


def manifest(embedder_id="fake", max_chunk_tokens=8) -> IndexManifest:
    return IndexManifest(
        index_name="t", embedder_id=embedder_id, embedding_dim=4, document_count=1, chunk_count=len(DEMO_CHUNKS),
        fingerprint="fp", max_chunk_tokens=max_chunk_tokens, created_at=datetime.now(UTC),
    )


CTX = RequestContext(request_id="r1")


def run(coro):
    return asyncio.run(coro)


def make():
    return retrieval.create_retriever(FakeEmbedder(), manifest())


def test_protocols():
    r = make()
    assert isinstance(r, Retriever)
    assert isinstance(retrieval.create_retrieval_evaluator(r), RetrievalEvaluator)


def test_chunk_limit_above_reranker_limit_is_index_not_ready():
    with pytest.raises(IndexNotReadyError):
        retrieval.create_retriever(FakeEmbedder(), manifest(max_chunk_tokens=100_000))


def test_retriever_exposes_injected_index():
    m = manifest()
    assert retrieval.create_retriever(FakeEmbedder(), m).index == m


def test_embedder_mismatch_is_index_not_ready():
    with pytest.raises(IndexNotReadyError):
        retrieval.create_retriever(FakeEmbedder(), manifest("other"))


@pytest.mark.parametrize("mode", list(RetrievalMode))
def test_result_rules(mode):
    res = run(make().retrieve(RetrievalRequest(query="장비 20GP 화면", mode=mode, k=2), CTX))
    assert 0 < len(res.chunks) <= 2
    assert [c.rank for c in res.chunks] == list(range(1, len(res.chunks) + 1))
    ids = [c.chunk.chunk_id for c in res.chunks]
    assert len(ids) == len(set(ids))


def test_empty_result_is_not_error():
    res = run(make().retrieve(RetrievalRequest(query="zzzz", mode=RetrievalMode.NAIVE, k=3), CTX))
    assert res.chunks == []


def test_invalid_input_propagates():
    with pytest.raises(InvalidInputError):
        run(make().retrieve(RetrievalRequest(query="단어 " * 20, mode=RetrievalMode.NAIVE, k=3), CTX))


def _item(id_, groups, q="장비 20GP"):
    return GoldenItem(
        id=id_, split=Split.DEVELOPMENT, question=q, expected_action=ExpectedAction.ANSWER, evidence_groups=groups
    )


def test_evaluator_scores_units_and_states():
    ev = retrieval.create_retrieval_evaluator(make())
    items = [
        _item("both", [[EvidenceRef(book_id="DEMO01", page=1)], [EvidenceRef(book_id="NOPE", page=1)]]),
        _item("clarify", []),
        _item("empty", [[EvidenceRef(book_id="DEMO01", page=1)]], q="zzzz"),
    ]
    page = run(ev.evaluate(items, RetrievalMode.HYBRID, 5, EvidenceUnit.PAGE, golden_fingerprint="gfp"))
    by = {m.item_id: m for m in page.items}
    assert by["both"].recall.value == 0.5 and by["both"].hit.value == 1.0
    assert by["clarify"].hit.state is ScoreState.NOT_APPLICABLE
    assert by["empty"].hit.value == 0.0  # 빈 결과도 0점으로 센다
    assert (page.scored, page.not_applicable, page.unavailable) == (2, 1, 0)
    assert page.unit is EvidenceUnit.PAGE and page.index_fingerprint == "fp" and page.index_name == "t"
    assert page.golden_fingerprint == "gfp"
    assert [m.item_id for m in page.items] == ["both", "clarify", "empty"]  # 입력 순서 유지
    assert run(ev.evaluate(items, RetrievalMode.HYBRID, 5, EvidenceUnit.PAGE)).golden_fingerprint is None

    # 페이지 단위는 [page_start, page_end] 포함 여부, 문서 단위는 book_id 만
    p8 = _item("p8", [[EvidenceRef(book_id="DEMO02", page=8)]], q="부산 로스앤젤레스")
    p9 = _item("p9", [[EvidenceRef(book_id="DEMO02", page=9)]], q="부산 로스앤젤레스")
    assert run(ev.evaluate([p8, p9], RetrievalMode.NAIVE, 5, EvidenceUnit.PAGE)).items[0].hit.value == 1.0
    assert run(ev.evaluate([p8, p9], RetrievalMode.NAIVE, 5, EvidenceUnit.PAGE)).items[1].hit.value == 0.0
    assert run(ev.evaluate([p9], RetrievalMode.NAIVE, 5, EvidenceUnit.DOCUMENT)).items[0].hit.value == 1.0


def test_evaluator_marks_failure_unavailable():
    ev = retrieval.create_retrieval_evaluator(make())
    bad = _item("bad", [[EvidenceRef(book_id="DEMO01", page=1)]], q="단어 " * 20)
    rep = run(ev.evaluate([bad], RetrievalMode.NAIVE, 3, EvidenceUnit.DOCUMENT))
    assert rep.items[0].hit.state is ScoreState.UNAVAILABLE
    assert rep.unavailable == 1 and rep.hit_at_k_mean is None


def test_mock_is_reachable_as_attribute_of_package():
    import retrieval

    assert retrieval.mock.__name__ == "retrieval.mock"
    assert hasattr(retrieval.mock, "__path__")
