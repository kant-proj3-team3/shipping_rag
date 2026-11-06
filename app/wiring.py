"""모듈 조립. common.entrypoints 의 시그니처만 사용한다. api 와 cli 가 공유한다."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import backend
import chunking
import retrieval
from common.interfaces import (
    AnswerEvaluator,
    Embedder,
    GoldenDatasetProvider,
    Indexer,
    QAService,
    RetrievalEvaluator,
    Retriever,
    SessionService,
)
from common.types import IndexManifest


def index_name() -> str:
    return os.environ.get("INDEX_NAME", "rag-dev-local")


@dataclass
class Base:
    embedder: Embedder
    indexer: Indexer
    golden: GoldenDatasetProvider


@dataclass
class Services:
    manifest: IndexManifest
    retriever: Retriever
    retrieval_evaluator: RetrievalEvaluator
    qa: QAService
    session: SessionService
    answer_evaluator: AnswerEvaluator


def build_base() -> Base:
    embedder = chunking.create_embedder()
    return Base(embedder, chunking.create_indexer(embedder), chunking.create_golden_provider())


def wait_for_manifest(indexer: Indexer, name: str, wait_seconds: float | None = None) -> IndexManifest | None:
    """인덱스가 준비될 때까지 재시도한다 (depends_on 은 Qdrant 준비 완료를 보장하지 않는다)."""
    if wait_seconds is None:
        wait_seconds = float(os.environ.get("INDEX_WAIT_SECONDS", "0"))
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            manifest = indexer.get_manifest(name)
        except Exception:
            manifest = None
        if manifest is not None or time.monotonic() >= deadline:
            return manifest
        time.sleep(2)


def build_services(base: Base, manifest: IndexManifest) -> Services:
    retriever = retrieval.create_retriever(base.embedder, manifest)
    return Services(
        manifest=manifest,
        retriever=retriever,
        retrieval_evaluator=retrieval.create_retrieval_evaluator(retriever),
        qa=backend.create_qa_service(retriever),
        session=backend.create_session_service(),
        answer_evaluator=backend.create_answer_evaluator(base.embedder),
    )
