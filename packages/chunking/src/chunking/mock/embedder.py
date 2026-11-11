"""목업 임베더: 해시 기반 결정적 벡터. 의미는 없고 계약(길이·한도·오류)만 지킨다."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from common.errors import IngestError, InvalidInputError

_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "


class MockEmbedder:
    def __init__(self, dimension: int = 16, max_input_tokens: int = 512) -> None:
        self._dim = dimension
        self._max = max_input_tokens

    @property
    def embedder_id(self) -> str:
        # 모델·접두사·정규화·최대 길이를 모두 구분한다
        return f"mock-hash-v1|prefix=e5|norm=l2|max={self._max}|dim={self._dim}"

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def max_input_tokens(self) -> int:
        return self._max

    def count_tokens(self, text: str) -> int:
        # 접두사 포함 입력을 공백 단위로 센다 (실제 토크나이저 아님)
        return len(text.split()) + 1

    def _vector(self, text: str) -> list[float]:
        raw: list[float] = []
        counter = 0
        while len(raw) < self._dim:
            digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
            raw.extend((b - 127.5) / 127.5 for b in digest)
            counter += 1
        vec = raw[: self._dim]
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for t in texts:
            if self.count_tokens(_PASSAGE_PREFIX + t) > self._max:
                raise IngestError(f"문서 입력이 임베더 한도({self._max} 토큰)를 넘는다")
            out.append(self._vector(_PASSAGE_PREFIX + t))
        return out

    def embed_query(self, text: str) -> list[float]:
        if self.count_tokens(_QUERY_PREFIX + text) > self._max:
            raise InvalidInputError(f"질문이 임베더 한도({self._max} 토큰)를 넘는다")
        return self._vector(_QUERY_PREFIX + text)
