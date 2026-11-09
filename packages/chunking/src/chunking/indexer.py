"""PDF 폴더 → 청크 → 임베딩 → Qdrant 색인 (Indexer 계약 구현).

단계: parse(PDF 읽기) → chunk(청킹·토큰 한도 확인) → embed(임베딩) → upsert(Qdrant 저장).
- 실패는 조용히 건너뛰지 않고 manifest.failures 에 남긴다: 읽을 수 없는 PDF, 중복 book_id, 본문이 없는 문서·페이지,
  토큰 한도를 넘는 청크.
- 임베딩이 끝난 뒤에 기존 인덱스를 지우고 쓴다. 재색인 도중 실패해도 이전 인덱스가 먼저 사라지지 않게 한다.
- 색인할 청크가 0개면 기존 인덱스를 건드리지 않고 IngestError 로 멈춘다 (documents_dir 를 잘못 줬을 때 등).
- manifest 는 맨 마지막에 저장한다. manifest 가 있으면 청크 저장이 끝난 인덱스라는 뜻이다.
- 설정: CHUNK_MAX_CHARS(청크 최대 글자 수, 기본 700). Qdrant 주소는 qdrant_store 참고.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from qdrant_client import QdrantClient

from common.errors import IngestError
from common.interfaces import Embedder, ProgressCallback
from common.types import Chunk, IndexBuildRequest, IndexManifest, IndexProgress, IngestFailure

from .chunker import DEFAULT_MAX_CHARS, chunk_page
from .pdf_parser import PageStructure, read_pdf
from .qdrant_store import QdrantIndexStore, create_qdrant_client

PARSER_VERSION = "pdfplumber-structure-v1"
_EMBED_BATCH = 256  # 진행 상황을 알리는 단위 (임베더 내부 배치와는 별개)


def fingerprint(chunks: list[Chunk]) -> str:
    """순서 있는 (chunk_id, text) 해시. 같은 청크 목록이면 같은 값이다."""
    payload = json.dumps([[c.chunk_id, c.text] for c in chunks], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PdfIndexer:
    def __init__(
        self,
        embedder: Embedder,
        client: QdrantClient | None = None,
        pdf_reader: Callable[[Path], list[PageStructure]] = read_pdf,
    ) -> None:
        self._embedder = embedder
        self._client = client  # 없으면 처음 쓸 때 환경변수로 만든다 (생성만으로 Qdrant 에 접속하지 않게)
        self._read_pdf = pdf_reader  # 테스트에서 PDF 없이 페이지 구역을 넣을 수 있다
        self._max_chars = int(os.environ.get("CHUNK_MAX_CHARS") or DEFAULT_MAX_CHARS)

    def _store(self) -> QdrantIndexStore:
        if self._client is None:
            self._client = create_qdrant_client()
        return QdrantIndexStore(self._client)

    # ── Indexer 계약 ──────────────────────────────────────────────────
    def build(self, request: IndexBuildRequest, progress: ProgressCallback | None = None) -> IndexManifest:
        store = self._store()
        name = request.index_name
        if store.exists(name) and not request.rebuild:
            raise IngestError(f"이미 있는 인덱스다: {name} (덮어쓰려면 rebuild=True)")

        def report(stage: str, done: int, total: int) -> None:
            if progress:
                progress(IndexProgress(stage=stage, done=done, total=total))

        failures: list[IngestFailure] = []
        chunks, document_count = self._parse_and_chunk(request.documents_dir, failures, report)
        chunks, observed_max = self._check_token_limit(chunks, failures, report)
        if not chunks:
            # 빈 인덱스를 "완성된 인덱스"로 저장하지 않는다. 기존 인덱스를 지우기 전에 멈춰서 이전 인덱스를 지킨다.
            reasons = "; ".join(f"{f.book_id}: {f.reason}" for f in failures[:5]) or "원인 미상"
            raise IngestError(f"색인할 청크가 없다 (기존 인덱스는 그대로 둔다): {reasons}")

        vectors: list[list[float]] = []
        for start in range(0, len(chunks), _EMBED_BATCH):
            vectors += self._embedder.embed_passages([c.text for c in chunks[start : start + _EMBED_BATCH]])
            report("embed", min(start + _EMBED_BATCH, len(chunks)), len(chunks))

        store.delete(name)
        store.write_chunks(name, chunks, vectors, self._embedder.dimension)
        report("upsert", len(chunks), len(chunks))

        manifest = IndexManifest(
            index_name=name,
            embedder_id=self._embedder.embedder_id,
            embedding_dim=self._embedder.dimension,
            document_count=document_count,
            chunk_count=len(chunks),
            fingerprint=fingerprint(chunks),
            max_chunk_tokens=self._embedder.max_input_tokens,
            created_at=datetime.now(UTC),
            params={
                "parser": PARSER_VERSION,
                "chunk_max_chars": self._max_chars,
                "chunk_unit": "page",  # 청크는 한 페이지 안에서만 만든다
                "context_line": True,
                "observed_max_chunk_tokens": observed_max,
                **request.params,
            },
            failures=failures,
        )
        store.save_manifest(manifest)
        return manifest

    def get_manifest(self, index_name: str) -> IndexManifest | None:
        return self._store().load_manifest(index_name)

    # ── 단계 ──────────────────────────────────────────────────────────
    def _parse_and_chunk(self, documents_dir: Path, failures: list[IngestFailure], report) -> tuple[list[Chunk], int]:
        if not documents_dir.is_dir():
            failures.append(IngestFailure(book_id="-", stage="parse", reason=f"문서 폴더가 없다: {documents_dir}"))
            return [], 0
        pdfs = sorted(documents_dir.glob("*.pdf"))
        if not pdfs:
            failures.append(IngestFailure(book_id="-", stage="parse", reason="PDF를 찾지 못했다"))

        chunks: list[Chunk] = []
        seen: set[str] = set()
        document_count = 0
        for done, pdf in enumerate(pdfs, start=1):
            book_id = pdf.stem  # 파일명에서 .pdf 를 뺀 값 (파일명은 바꾸지 않는다)
            if book_id.lower() in seen:
                failures.append(IngestFailure(book_id=book_id, stage="parse", reason=f"중복 book_id: {pdf.name}"))
                continue
            seen.add(book_id.lower())
            try:
                pages = self._read_pdf(pdf)
            except Exception as exc:  # 깨진 PDF 하나 때문에 전체를 멈추지 않는다
                failures.append(IngestFailure(book_id=book_id, stage="parse", reason=f"PDF를 읽지 못했다: {exc}"))
                continue

            doc_chunks: list[Chunk] = []
            empty_pages: list[int] = []
            for page in pages:
                page_chunks = chunk_page(book_id, pdf.name, page, self._max_chars)
                if not page_chunks:
                    empty_pages.append(page.page)
                doc_chunks += page_chunks
            if not doc_chunks:
                failures.append(IngestFailure(book_id=book_id, stage="parse", reason="본문이 없다 (색인에서 뺀다)"))
                continue
            if empty_pages:
                failures.append(IngestFailure(book_id=book_id, stage="chunk", reason=f"본문이 없는 페이지: {empty_pages}"))
            chunks += doc_chunks
            document_count += 1
            report("parse", done, len(pdfs))
        return chunks, document_count

    def _check_token_limit(self, chunks: list[Chunk], failures: list[IngestFailure], report) -> tuple[list[Chunk], int]:
        """모든 청크가 임베더 한도(접두사 포함) 이하인지 확인한다. 넘는 청크는 기록하고 뺀다 (조용히 자르지 않는다)."""
        limit = self._embedder.max_input_tokens
        kept: list[Chunk] = []
        observed_max = 0
        for c in chunks:
            n = self._embedder.count_tokens(c.text)
            if n > limit:
                failures.append(IngestFailure(book_id=c.book_id, stage="chunk", reason=f"{c.chunk_id}: {n}토큰 > {limit}"))
                continue
            observed_max = max(observed_max, n)
            kept.append(c)
        report("chunk", len(kept), len(chunks))
        return kept, observed_max
