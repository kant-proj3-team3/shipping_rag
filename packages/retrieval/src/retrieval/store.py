"""Qdrant 클라이언트 생성. 설정은 환경변수에서만 읽는다(.env 는 app/ 이 읽는다)."""

from __future__ import annotations

import os

from qdrant_client import QdrantClient


def create_qdrant_client() -> QdrantClient:
    # QDRANT_PATH 는 서버 없이 단독 개발·테스트할 때만 쓴다(한 번에 한 프로세스). 있으면 서버 주소보다 우선한다.
    path = os.environ.get("QDRANT_PATH")
    if path:
        return QdrantClient(path=path)
    return QdrantClient(url=os.environ.get("QDRANT_URL", "http://localhost:6333"))
