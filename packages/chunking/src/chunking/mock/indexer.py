"""목업 인덱서: PDF를 읽지 않는다. 폴더의 PDF 파일 수만 세고 고정된 데모 신원을 기록한다.

실제 인덱스는 Qdrant에 남아 프로세스가 바뀌어도 유지된다. 이를 흉내 내려고 manifest 를 로컬 JSON 으로 저장한다
(MOCK_INDEX_DIR, 기본 ./.mock_index). `index` 를 실행하기 전에는 get_manifest 가 None 이다 (인덱스 없음).
데이터 없이 화면·API 만 시연할 때는 MOCK_INDEX_READY=1 로 항상 준비된 데모 인덱스를 돌려받는다.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from common.errors import IngestError
from common.interfaces import Embedder, ProgressCallback
from common.types import IndexBuildRequest, IndexManifest, IndexProgress, IngestFailure

# 데모 인덱스의 청크 수 (retrieval 목업의 데모 청크와 같은 개수)
_DEMO_CHUNK_COUNT = 4
_MAX_CHUNK_TOKENS = 256


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes"}


class MockIndexer:
    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    # ── 저장 ──────────────────────────────────────────────────────────
    @staticmethod
    def _path(index_name: str) -> Path:
        base = Path(os.environ.get("MOCK_INDEX_DIR", ".mock_index"))
        return base / (re.sub(r"[^A-Za-z0-9_.-]", "_", index_name) + ".json")

    def _load(self, index_name: str) -> IndexManifest | None:
        path = self._path(index_name)
        if not path.is_file():
            return None
        return IndexManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def _save(self, manifest: IndexManifest) -> None:
        path = self._path(manifest.index_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    def _manifest(self, index_name: str, documents: int, failures: list[IngestFailure]) -> IndexManifest:
        fingerprint = hashlib.sha256(f"mock:{index_name}:{documents}".encode()).hexdigest()
        return IndexManifest(
            index_name=index_name,
            embedder_id=self._embedder.embedder_id,
            embedding_dim=self._embedder.dimension,
            document_count=documents,
            chunk_count=_DEMO_CHUNK_COUNT,
            fingerprint=fingerprint,
            max_chunk_tokens=min(_MAX_CHUNK_TOKENS, self._embedder.max_input_tokens),
            created_at=datetime.now(UTC),
            params={"mock": True},
            failures=failures,
        )

    # ── Indexer 계약 ──────────────────────────────────────────────────
    def build(self, request: IndexBuildRequest, progress: ProgressCallback | None = None) -> IndexManifest:
        if self._load(request.index_name) is not None and not request.rebuild:
            raise IngestError(f"이미 있는 인덱스다: {request.index_name} (덮어쓰려면 rebuild=True)")
        pdfs = sorted(request.documents_dir.glob("*.pdf")) if request.documents_dir.is_dir() else []
        failures: list[IngestFailure] = []
        if not pdfs:
            failures.append(IngestFailure(book_id="-", stage="parse", reason="PDF를 찾지 못했다"))
        for stage in ("parse", "chunk", "embed", "upsert"):
            if progress:
                progress(IndexProgress(stage=stage, done=len(pdfs), total=len(pdfs)))
        manifest = self._manifest(request.index_name, len(pdfs), failures)
        self._save(manifest)
        return manifest

    def get_manifest(self, index_name: str) -> IndexManifest | None:
        built = self._load(index_name)
        if built is not None:
            return built
        if _truthy(os.environ.get("MOCK_INDEX_READY")):
            return self._manifest(index_name, 0, [])  # 시연용: 저장하지 않는 데모 인덱스
        return None
