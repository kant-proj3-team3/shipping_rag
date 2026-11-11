"""임베더·인덱서 단위 테스트. 모델·Qdrant 서버 없이 돈다 (가짜 모델, 가짜 페이지 구역, 메모리 Qdrant)."""

from pathlib import Path

import numpy as np
import pytest
from qdrant_client import QdrantClient

import chunking
from chunking.embedder import E5Embedder
from chunking.chunker import chunk_page
from chunking.indexer import PdfIndexer, fingerprint
from chunking.mock import MockEmbedder
from chunking.pdf_parser import PageStructure
from common.errors import IngestError, InvalidInputError
from common.interfaces import Embedder, Indexer
from common.types import Chunk, IndexBuildRequest


def _page(page=9, rows=8) -> PageStructure:
    return PageStructure(
        page=page,
        title="N1 터미널 보관료 요율 자료집",
        section="기본 요율 행",
        subtitle="기본 요율 원문",
        intro="20GP는 무료기간 3일이다. 40GP는 무료기간 4일이다.",
        table_title="기본 요율 원문 — 업무 확인 대장",
        header=["업무 기록번호", "대상", "확인 항목", "일자·원자료", "처리 상태"],
        rows=[[f"IS12-009-0{i}", "해솔무역 40GP / N1", "STD / 2027-01-01", "기본 4일 USD 68/일", "확인"] for i in range(1, rows + 1)],
        memo="접수일이나 청구일을 실제 양하일로 해석하지 않는다.",
        summary="이 표의 20GP·STD 행을 사용한다. 반출일 미확인이어도 조회할 수 있다.",
        table_count=1,
    )


# ── 임베더 ────────────────────────────────────────────────────────────
class _FakeTokenizer:
    def __call__(self, text, add_special_tokens=True):
        return {"input_ids": [0] * (len(text.split()) + 2)}


class _FakeModel:
    tokenizer = _FakeTokenizer()

    def get_sentence_embedding_dimension(self):
        return 4

    def encode(self, texts, **kwargs):
        assert kwargs["normalize_embeddings"] is True
        return np.ones((len(texts), 4)) / 2


def test_e5_embedder_contract(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MAX_TOKENS", "10")
    emb = E5Embedder(model=_FakeModel())
    assert isinstance(emb, Embedder)
    assert emb.dimension == 4 and emb.max_input_tokens == 10
    assert "prefix=e5" in emb.embedder_id and "max=10" in emb.embedder_id and "dim=4" in emb.embedder_id
    assert emb.count_tokens("a b") == 5  # "passage:" + a + b + 특수 토큰 2개 (접두사 포함)
    assert len(emb.embed_query("질문")) == 4
    assert [len(v) for v in emb.embed_passages(["a", "b"])] == [4, 4]


def test_e5_embedder_does_not_truncate_silently(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MAX_TOKENS", "10")
    emb = E5Embedder(model=_FakeModel())
    with pytest.raises(InvalidInputError):
        emb.embed_query("단어 " * 20)
    with pytest.raises(IngestError):
        emb.embed_passages(["단어 " * 20])


def test_embedder_id_changes_with_settings(monkeypatch):
    a = E5Embedder(model=_FakeModel()).embedder_id
    monkeypatch.setenv("EMBEDDING_MAX_TOKENS", "256")
    assert E5Embedder(model=_FakeModel()).embedder_id != a


def test_fingerprint_is_deterministic():
    assert fingerprint(chunk_page("IS12", "IS12.pdf", _page())) == fingerprint(chunk_page("IS12", "IS12.pdf", _page()))


# ── 인덱서 ────────────────────────────────────────────────────────────
def _docs(tmp_path: Path, names) -> Path:
    d = tmp_path / "documents"
    d.mkdir()
    for n in names:
        (d / n).write_bytes(b"%PDF-fake")
    return d


def _reader(path: Path) -> list[PageStructure]:
    if path.stem == "BROKEN":
        raise ValueError("깨진 PDF")
    if path.stem == "EMPTY":
        return [PageStructure(page=1)]
    return [_page(page=1), _page(page=2)]


def _indexer(client=None):
    return PdfIndexer(MockEmbedder(dimension=8, max_input_tokens=512), client=client or QdrantClient(":memory:"), pdf_reader=_reader)


def test_indexer_build_and_manifest_roundtrip(tmp_path):
    client = QdrantClient(":memory:")
    indexer = _indexer(client)
    assert isinstance(indexer, Indexer)
    stages = []
    manifest = indexer.build(
        IndexBuildRequest(documents_dir=_docs(tmp_path, ["IS01.pdf", "IS02.pdf"]), index_name="t-index"),
        progress=lambda p: stages.append(p.stage),
    )
    assert manifest.document_count == 2 and manifest.chunk_count == 16  # 문서 2 × 페이지 2 × 청크 4
    assert manifest.embedding_dim == 8 and manifest.failures == []
    assert {"parse", "chunk", "embed", "upsert"} <= set(stages)
    assert indexer.get_manifest("t-index") == manifest  # 다른 호출에서도 같은 신원을 읽는다
    assert indexer.get_manifest("no-such") is None

    points, _ = client.scroll("t-index", limit=100, with_payload=True)
    restored = [Chunk.model_validate(p.payload) for p in points]  # 검색 모듈과 같은 방식으로 복원된다
    assert len(restored) == 16 and {c.book_id for c in restored} == {"IS01", "IS02"}
    assert client.get_collection("t-index").config.params.vectors.size == 8


def test_indexer_records_failures_instead_of_skipping(tmp_path):
    manifest = _indexer().build(
        IndexBuildRequest(documents_dir=_docs(tmp_path, ["IS01.pdf", "BROKEN.pdf", "EMPTY.pdf"]), index_name="t-fail")
    )
    reasons = {f.book_id: f.reason for f in manifest.failures}
    assert manifest.document_count == 1
    assert "읽지 못했다" in reasons["BROKEN"] and "본문이 없다" in reasons["EMPTY"]


def test_indexer_refuses_existing_index_without_rebuild(tmp_path):
    indexer = _indexer()
    request = IndexBuildRequest(documents_dir=_docs(tmp_path, ["IS01.pdf"]), index_name="t-dup")
    first = indexer.build(request)
    with pytest.raises(IngestError):
        indexer.build(request)
    again = indexer.build(request.model_copy(update={"rebuild": True}))
    assert again.fingerprint == first.fingerprint and again.chunk_count == first.chunk_count


def test_indexer_excludes_chunks_over_token_limit(tmp_path):
    indexer = PdfIndexer(MockEmbedder(dimension=8, max_input_tokens=5), client=QdrantClient(":memory:"), pdf_reader=_reader)
    # 모든 청크가 한도를 넘으면 색인할 청크가 0개가 되어 멈춘다. 원인(토큰 초과)이 메시지에 남는다
    with pytest.raises(IngestError, match="토큰"):
        indexer.build(IndexBuildRequest(documents_dir=_docs(tmp_path, ["IS01.pdf"]), index_name="t-limit"))


@pytest.mark.parametrize(("folder", "reason"), [("nope", "문서 폴더가 없다"), ("empty", "PDF를 찾지 못했다")])
def test_wrong_documents_dir_keeps_previous_index(tmp_path, folder, reason):
    # 잘못된 폴더로 rebuild=True 를 해도 기존 인덱스와 manifest 가 그대로 남아야 한다
    client = QdrantClient(":memory:")
    indexer = _indexer(client)
    first = indexer.build(IndexBuildRequest(documents_dir=_docs(tmp_path, ["IS01.pdf"]), index_name="t-keep"))
    (tmp_path / "empty").mkdir()
    with pytest.raises(IngestError, match=reason):
        indexer.build(IndexBuildRequest(documents_dir=tmp_path / folder, index_name="t-keep", rebuild=True))
    assert indexer.get_manifest("t-keep") == first
    assert client.count("t-keep").count == first.chunk_count


# ── 진입점 ────────────────────────────────────────────────────────────
def test_entrypoints_switch_to_real_embedder_and_indexer(monkeypatch):
    monkeypatch.setenv("CHUNKING_IMPL", "real")
    emb = chunking.create_embedder()
    assert isinstance(emb, E5Embedder)  # 생성만으로 모델을 내려받지 않는다
    assert isinstance(chunking.create_indexer(emb), PdfIndexer)  # 생성만으로 Qdrant 에 접속하지 않는다


def test_default_is_mock(monkeypatch):
    monkeypatch.delenv("CHUNKING_IMPL", raising=False)
    assert not isinstance(chunking.create_embedder(), E5Embedder)
