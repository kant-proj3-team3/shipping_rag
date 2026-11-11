"""모듈 진입점 시그니처. 각 모듈 패키지는 아래 이름의 함수를 최상위에 노출한다.

- app/ 은 이 함수들로만 모듈을 조립한다. (모듈 내부 클래스를 직접 import 하지 않는다)
- 설정(키·주소·모델명 등)은 각 모듈이 환경변수로 읽는다. 인자로 받지 않는다.
- 인자는 '다른 모듈에서 오는 협력 객체'뿐이다.

    chunking.create_embedder()                         -> Embedder
    chunking.create_indexer(embedder)                  -> Indexer
    chunking.create_golden_provider()                  -> GoldenDatasetProvider
    retrieval.create_retriever(embedder, index)        -> Retriever
    retrieval.create_retrieval_evaluator(retriever)    -> RetrievalEvaluator
    backend.create_qa_service(retriever)               -> QAService
    backend.create_session_service()                   -> SessionService
    backend.create_answer_evaluator(embedder)          -> AnswerEvaluator   # embedder: answer_relevancy를 쓸 때만, 아니면 None
    backend.create_router(qa_service, session_service, index) -> fastapi.APIRouter
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .interfaces import (
    AnswerEvaluator,
    Embedder,
    GoldenDatasetProvider,
    Indexer,
    QAService,
    Retriever,
    RetrievalEvaluator,
    SessionService,
)
from .types import IndexManifest

CreateEmbedder = Callable[[], Embedder]
CreateIndexer = Callable[[Embedder], Indexer]
CreateGoldenProvider = Callable[[], GoldenDatasetProvider]
CreateRetriever = Callable[[Embedder, IndexManifest], Retriever]
CreateRetrievalEvaluator = Callable[[Retriever], RetrievalEvaluator]
CreateQAService = Callable[[Retriever], QAService]
CreateSessionService = Callable[[], SessionService]
CreateAnswerEvaluator = Callable[[Embedder | None], AnswerEvaluator]
CreateRouter = Callable[[QAService, SessionService, IndexManifest], Any]  # fastapi.APIRouter (common은 fastapi에 의존하지 않는다)
