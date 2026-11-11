"""모듈 조립. common.entrypoints 의 시그니처만 사용한다. api 와 cli 가 공유한다."""

from __future__ import annotations

import os
import re
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
from common.errors import InvalidInputError
from common.types import IndexManifest

# 모듈별 구현 선택 환경변수. 같은 값(real/mock)을 세 모듈에 한꺼번에 적용하는 것이 APP_IMPL 이다.
MODULE_IMPL_VARS = ("CHUNKING_IMPL", "RETRIEVAL_IMPL", "BACKEND_IMPL")
DEFAULT_APP_IMPL = "real"
_INDEX_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def apply_impl_default() -> str:
    """`APP_IMPL`(기본 `real`)을 세 모듈의 `*_IMPL` 기본값으로 적용한다. 이미 설정된 모듈별 값은 덮어쓰지 않는다.

    app 을 실행하면(api·cli) 실제 구현으로 조립된다. 목업으로 돌리려면 `APP_IMPL=mock`, 모듈 하나만 바꾸려면
    그 모듈의 `*_IMPL` 을 직접 준다. 모듈(`packages/*`)의 기본값은 그대로 목업이라 모듈 단위 테스트·CI 는 영향이 없다.
    """
    impl = (os.environ.get("APP_IMPL") or DEFAULT_APP_IMPL).strip().lower()
    if impl not in {"real", "mock"}:
        raise InvalidInputError(f"APP_IMPL 은 real 또는 mock 이어야 한다(받은 값: {impl!r})")
    for var in MODULE_IMPL_VARS:
        os.environ.setdefault(var, impl)
    return impl


def index_name() -> str:
    """색인(컬렉션) 이름. `.env.example` 의 자리표시자(`<본인이름>`)가 그대로 남아 있으면 알려 준다."""
    name = os.environ.get("INDEX_NAME", "rag-dev-local")
    if not _INDEX_NAME.match(name):
        raise InvalidInputError(
            f"INDEX_NAME={name!r} 는 컬렉션 이름으로 쓸 수 없다. 영문·숫자·_·-·. 만 쓴다(예: rag-dev-내이름). "
            ".env.example 의 자리표시자를 고치지 않았는지 확인한다"
        )
    return name


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
