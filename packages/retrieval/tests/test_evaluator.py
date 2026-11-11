"""GroupRetrievalEvaluator 단위 테스트. 검색기는 이 파일 안의 가짜를 쓴다(다른 모듈 import 금지)."""

import asyncio
from datetime import UTC, datetime

import pytest

import retrieval
from common.errors import IndexNotReadyError, RetrievalError
from common.types import (
    Chunk,
    EvidenceRef,
    EvidenceUnit,
    ExpectedAction,
    GoldenItem,
    IndexManifest,
    RetrievalMode,
    RetrievalResult,
    RetrievedChunk,
    ScoreState,
    Split,
)
from retrieval.evaluator import GroupRetrievalEvaluator

MANIFEST = IndexManifest(
    index_name="idx", embedder_id="fake", embedding_dim=2, document_count=1, chunk_count=1,
    fingerprint="fp-1", max_chunk_tokens=8, created_at=datetime.now(UTC),
)


def chunk(book="B1", start=1, end=None, cid=None) -> Chunk:
    end = end or start
    return Chunk(chunk_id=cid or f"{book}-p{start}-{end}", book_id=book, file_name=f"{book}.pdf",
                 page_start=start, page_end=end, text="본문")


class FakeRetriever:
    """질문별로 정해 둔 청크를 돌려주는 가짜 검색기. fail 에 든 질문은 error(기본 RetrievalError)를 낸다."""

    def __init__(self, by_question: dict[str, list[Chunk]], fail: set[str] = frozenset(),
                 error: type[Exception] = RetrievalError):
        self.index = MANIFEST
        self._by_question = by_question
        self._fail = fail
        self._error = error
        self.requests = []

    async def retrieve(self, request, ctx):
        self.requests.append(request)
        if request.query in self._fail:
            raise self._error("boom")
        chunks = self._by_question.get(request.query, [])[: request.k]
        return RetrievalResult(
            mode=request.mode, k=request.k,
            chunks=[RetrievedChunk(rank=i, score=1.0, chunk=c) for i, c in enumerate(chunks, start=1)],
        )


def item(qid, question, groups) -> GoldenItem:
    return GoldenItem(
        id=qid, split=Split.DEVELOPMENT, question=question, expected_action=ExpectedAction.ANSWER,
        evidence_groups=[[EvidenceRef(book_id=b, page=p) for b, p in g] for g in groups],
    )


def run(retriever, items, k=5, unit=EvidenceUnit.PAGE, golden_fp=None):
    ev = GroupRetrievalEvaluator(retriever)
    return asyncio.run(ev.evaluate(items, RetrievalMode.NAIVE, k, unit, golden_fp))


def test_그룹끼리는_AND_그룹_안은_OR():
    # 그룹0: B1 p1, 그룹1: (B2 p2 또는 B3 p9). 검색 결과가 B1 p1 과 B3 p9 를 덮는다.
    r = FakeRetriever({"q": [chunk("B1", 1), chunk("B3", 9)]})
    report = run(r, [item("i1", "q", [[("B1", 1)], [("B2", 2), ("B3", 9)]])])
    m = report.items[0]
    assert m.satisfied_groups == [0, 1]
    assert m.hit.value == 1.0 and m.recall.value == 1.0


def test_일부_그룹만_만족하면_recall이_줄어든다():
    r = FakeRetriever({"q": [chunk("B1", 1)]})
    m = run(r, [item("i1", "q", [[("B1", 1)], [("B2", 2)]])]).items[0]
    assert m.hit.value == 1.0 and m.recall.value == 0.5 and m.satisfied_groups == [0]


def test_document_단위는_book_id만_보고_page_단위는_페이지_범위를_본다():
    r = FakeRetriever({"q": [chunk("B1", 5)]})
    it = item("i1", "q", [[("B1", 7)]])  # 같은 문서의 다른 페이지
    assert run(r, [it], unit=EvidenceUnit.DOCUMENT).items[0].hit.value == 1.0
    assert run(r, [it], unit=EvidenceUnit.PAGE).items[0].hit.value == 0.0


def test_청크가_여러_페이지에_걸치면_범위_안의_페이지가_일치한다():
    r = FakeRetriever({"q": [chunk("B1", 3, 5)]})
    assert run(r, [item("i1", "q", [[("B1", 4)]])]).items[0].hit.value == 1.0


def test_같은_근거가_여러_청크에서_나와도_한_번만_센다():
    r = FakeRetriever({"q": [chunk("B1", 1, cid="a"), chunk("B1", 1, cid="b")]})
    m = run(r, [item("i1", "q", [[("B1", 1)], [("B2", 2)]])]).items[0]
    assert m.satisfied_groups == [0] and m.recall.value == 0.5


def test_검색_결과가_비어도_근거가_있으면_0점으로_센다():
    report = run(FakeRetriever({}), [item("i1", "q", [[("B1", 1)]])])
    assert report.items[0].hit.state is ScoreState.SCORED
    assert report.items[0].hit.value == 0.0 and report.scored == 1
    assert report.hit_at_k_mean == 0.0


def test_근거_그룹이_없으면_not_applicable이고_평균에서_뺀다():
    r = FakeRetriever({"q1": [chunk("B1", 1)]})
    report = run(r, [item("i1", "q1", [[("B1", 1)]]), item("i2", "q2", [])])
    assert report.items[1].hit.state is ScoreState.NOT_APPLICABLE and report.items[1].hit.value is None
    assert (report.scored, report.not_applicable, report.unavailable) == (1, 1, 0)
    assert report.hit_at_k_mean == 1.0
    assert [req.query for req in r.requests] == ["q1"]  # 근거 없는 문항은 검색하지 않는다


def test_호출_실패는_unavailable이고_평균에서_뺀다():
    r = FakeRetriever({"q1": [chunk("B1", 1)]}, fail={"q2"})
    report = run(r, [item("i1", "q1", [[("B1", 1)]]), item("i2", "q2", [[("B1", 1)]])])
    assert report.items[1].hit.state is ScoreState.UNAVAILABLE and "RetrievalError" in report.items[1].hit.reason
    assert (report.scored, report.unavailable) == (1, 1)
    assert report.hit_at_k_mean == 1.0  # 실패 문항을 0점으로 섞지 않는다


def test_IndexNotReadyError는_문항별로_삼키지_않고_전파한다():
    r = FakeRetriever({"q1": [chunk("B1", 1)]}, fail={"q2"}, error=IndexNotReadyError)
    with pytest.raises(IndexNotReadyError):
        run(r, [item("i1", "q1", [[("B1", 1)]]), item("i2", "q2", [[("B1", 1)]])])


def test_모든_문항의_검색이_실패하면_RetrievalError로_알린다():
    r = FakeRetriever({}, fail={"q1", "q2"})
    with pytest.raises(RetrievalError, match="boom"):  # 첫 사유가 메시지에 남는다
        run(r, [item("i1", "q1", [[("B1", 1)]]), item("i2", "q2", [[("B1", 1)]])])


def test_근거_없는_문항만_있으면_오류_없이_평균은_None():
    report = run(FakeRetriever({}), [item("i1", "q1", [])])
    assert (report.scored, report.not_applicable, report.unavailable) == (0, 1, 0)
    assert report.hit_at_k_mean is None


def test_평가할_문항이_없으면_평균은_None():
    report = run(FakeRetriever({}), [item("i1", "q", [])])
    assert report.hit_at_k_mean is None and report.recall_at_k_mean is None


def test_보고서에_인덱스_신원과_골든_지문과_단위가_남는다():
    report = run(FakeRetriever({}), [item("i1", "q", [[("B1", 1)]])], k=3, unit=EvidenceUnit.DOCUMENT, golden_fp="g-1")
    assert (report.index_name, report.index_fingerprint, report.golden_fingerprint) == ("idx", "fp-1", "g-1")
    assert (report.k, report.unit, report.mode) == (3, EvidenceUnit.DOCUMENT, RetrievalMode.NAIVE)


def test_입력_순서가_유지되고_질문만_검색에_전달된다():
    r = FakeRetriever({})
    items = [item(f"i{n}", f"q{n}", [[("B1", n)]]) for n in range(1, 6)]
    report = run(r, items)
    assert [m.item_id for m in report.items] == [f"i{n}" for n in range(1, 6)]
    assert all(set(req.model_dump()) == {"query", "mode", "k"} for req in r.requests)


@pytest.mark.parametrize("k", [0, 51, -1])
def test_k가_범위를_벗어나면_ValueError(k):
    with pytest.raises(ValueError):
        run(FakeRetriever({}), [item("i1", "q", [[("B1", 1)]])], k=k)


@pytest.mark.parametrize("n", [0, -1])
def test_max_concurrency가_1보다_작으면_ValueError(n):
    with pytest.raises(ValueError):
        GroupRetrievalEvaluator(FakeRetriever({}), max_concurrency=n)


def test_RETRIEVAL_IMPL이_없으면_목업을_돌려준다(monkeypatch):
    monkeypatch.delenv("RETRIEVAL_IMPL", raising=False)
    from retrieval.mock import MockRetrievalEvaluator
    assert isinstance(retrieval.create_retrieval_evaluator(FakeRetriever({})), MockRetrievalEvaluator)


def test_RETRIEVAL_IMPL이_real이면_실제_평가기를_돌려준다(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_IMPL", "real")
    assert isinstance(retrieval.create_retrieval_evaluator(FakeRetriever({})), GroupRetrievalEvaluator)
