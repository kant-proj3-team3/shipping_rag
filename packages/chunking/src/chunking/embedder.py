"""E5 임베더 (sentence-transformers). 설정은 환경변수로 읽는다.

- EMBEDDING_MODEL      기본 intfloat/multilingual-e5-base (small/base/large 비교에서 base 가 k=5 기준 가장 균형이 좋았다)
- EMBEDDING_MAX_TOKENS 기본 512 (e5 의 최대 입력 길이). 접두사를 포함한 상한이다
- EMBEDDING_DEVICE     cuda / cpu. 비우면 GPU 가 있으면 cuda
- EMBEDDING_BATCH_SIZE 기본 64
- RAG_MODEL_CACHE      모델 다운로드 위치

E5 규칙: 문서에는 "passage: ", 질의에는 "query: " 를 붙이고, 벡터는 길이 1로 정규화한다(코사인 유사도).
한도를 넘는 입력은 조용히 자르지 않는다: 문서는 IngestError, 질의는 InvalidInputError.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

from common.errors import IngestError, InvalidInputError

PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "
DEFAULT_MODEL = "intfloat/multilingual-e5-base"
DEFAULT_MAX_TOKENS = 512
DEFAULT_BATCH_SIZE = 64


class E5Embedder:
    def __init__(self, model: Any | None = None) -> None:
        self._model_name = os.environ.get("EMBEDDING_MODEL") or DEFAULT_MODEL
        self._max_tokens = int(os.environ.get("EMBEDDING_MAX_TOKENS") or DEFAULT_MAX_TOKENS)
        self._batch_size = int(os.environ.get("EMBEDDING_BATCH_SIZE") or DEFAULT_BATCH_SIZE)
        self._device = os.environ.get("EMBEDDING_DEVICE") or None
        self._cache_dir = os.environ.get("RAG_MODEL_CACHE") or None
        self._model = model  # 테스트에서 가짜 모델을 넣을 수 있다. 없으면 처음 쓸 때 불러온다

    # 모델은 처음 필요할 때 불러온다 (생성만으로 수백 MB 를 내려받지 않게)
    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            device = self._device
            if device is None:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = SentenceTransformer(self._model_name, device=device, cache_folder=self._cache_dir)
            self._model.max_seq_length = self._max_tokens
        return self._model

    # ── Embedder 계약 ──────────────────────────────────────────────────
    @property
    def embedder_id(self) -> str:
        # 모델·접두사·정규화·최대 길이·차원을 모두 구분한다. 하나라도 바뀌면 다른 인덱스다
        return f"{self._model_name}|prefix=e5|norm=l2|max={self._max_tokens}|dim={self.dimension}"

    @property
    def dimension(self) -> int:
        model = self._load()
        get_dim = getattr(model, "get_sentence_embedding_dimension", None) or model.get_embedding_dimension
        return int(get_dim())

    @property
    def max_input_tokens(self) -> int:
        return self._max_tokens

    def count_tokens(self, text: str) -> int:
        """문서 접두사("passage: ")를 붙인 입력의 토큰 수 (특수 토큰 포함). 인덱서가 청크 길이를 이 값으로 잰다."""
        return self._token_len(PASSAGE_PREFIX + text)

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        for i, text in enumerate(texts):
            n = self.count_tokens(text)
            if n > self._max_tokens:
                raise IngestError(f"문서 입력 {i}번이 임베더 한도를 넘는다 ({n} > {self._max_tokens} 토큰)")
        return self._encode([PASSAGE_PREFIX + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        n = self._token_len(QUERY_PREFIX + text)
        if n > self._max_tokens:
            raise InvalidInputError(f"질문이 임베더 한도를 넘는다 ({n} > {self._max_tokens} 토큰)")
        return self._encode([QUERY_PREFIX + text])[0]

    # ── 내부 ──────────────────────────────────────────────────────────
    def _token_len(self, text: str) -> int:
        return len(self._load().tokenizer(text, add_special_tokens=True)["input_ids"])

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load().encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [list(map(float, v)) for v in vectors]
