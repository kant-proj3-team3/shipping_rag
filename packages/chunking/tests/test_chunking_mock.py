from pathlib import Path

import pytest

import chunking
from common.errors import IngestError, InvalidInputError
from common.interfaces import Embedder, GoldenDatasetProvider, Indexer
from common.types import IndexBuildRequest, Split


def test_entrypoints_satisfy_protocols():
    emb = chunking.create_embedder()
    assert isinstance(emb, Embedder)
    assert isinstance(chunking.create_indexer(emb), Indexer)
    assert isinstance(chunking.create_golden_provider(), GoldenDatasetProvider)


def test_embedder_dimension_and_determinism():
    emb = chunking.create_embedder()
    v = emb.embed_query("안녕")
    assert len(v) == emb.dimension
    assert v == emb.embed_query("안녕")
    assert [len(x) for x in emb.embed_passages(["a", "b"])] == [emb.dimension] * 2


def test_embedder_limits_not_truncated_silently():
    emb = chunking.create_embedder()
    too_long = "단어 " * (emb.max_input_tokens + 1)
    with pytest.raises(InvalidInputError):
        emb.embed_query(too_long)
    with pytest.raises(IngestError):
        emb.embed_passages([too_long])


@pytest.fixture(autouse=True)
def _isolated_index(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_INDEX_DIR", str(tmp_path / "idx"))
    monkeypatch.delenv("MOCK_INDEX_READY", raising=False)


def test_manifest_is_none_until_built_and_survives_new_instances(tmp_path: Path):
    emb = chunking.create_embedder()
    assert chunking.create_indexer(emb).get_manifest("x") is None
    built = chunking.create_indexer(emb).build(IndexBuildRequest(documents_dir=tmp_path, index_name="x"))
    again = chunking.create_indexer(emb).get_manifest("x")  # 다른 인스턴스(=다른 프로세스)에서도 보인다
    assert again == built


def test_ready_flag_gives_demo_index_without_persisting(monkeypatch):
    monkeypatch.setenv("MOCK_INDEX_READY", "1")
    idx = chunking.create_indexer(chunking.create_embedder())
    assert idx.get_manifest("demo") is not None
    monkeypatch.delenv("MOCK_INDEX_READY")
    assert idx.get_manifest("demo") is None


def test_indexer_rebuild_rule_and_progress(tmp_path: Path):
    (tmp_path / "A01.pdf").write_bytes(b"%PDF")
    idx = chunking.create_indexer(chunking.create_embedder())
    stages = []
    m = idx.build(IndexBuildRequest(documents_dir=tmp_path, index_name="t"), progress=lambda p: stages.append(p.stage))
    assert m.document_count == 1 and m.failures == []
    assert stages == ["parse", "chunk", "embed", "upsert"]
    with pytest.raises(IngestError):
        idx.build(IndexBuildRequest(documents_dir=tmp_path, index_name="t"))
    idx.build(IndexBuildRequest(documents_dir=tmp_path, index_name="t", rebuild=True))


def test_indexer_records_failure_when_no_pdf(tmp_path: Path):
    idx = chunking.create_indexer(chunking.create_embedder())
    m = idx.build(IndexBuildRequest(documents_dir=tmp_path, index_name="empty"))
    assert m.failures  # 조용히 건너뛰지 않는다


def test_golden_excludes_security_by_default():
    g = chunking.create_golden_provider()
    assert all(i.split is not Split.SECURITY for i in g.load())
    assert any(i.split is Split.SECURITY for i in g.load([Split.SECURITY]))
    assert g.fingerprint() == g.fingerprint() != g.fingerprint([Split.SECURITY])
    ids = [i.id for i in g.load([s for s in Split])]
    assert len(ids) == len(set(ids))


def test_mock_is_reachable_as_attribute_of_package():
    import chunking

    assert chunking.mock.__name__ == "chunking.mock"
    assert hasattr(chunking.mock, "__path__")
