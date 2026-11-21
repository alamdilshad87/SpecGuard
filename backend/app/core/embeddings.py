"""Text embeddings for semantic retrieval.

``FastEmbedEmbedder`` runs a small open-source model (BAAI/bge-small-en-v1.5, 384 dims)
locally through ONNX Runtime: no API keys, and nothing leaves the machine. The model is
downloaded once and cached; the Docker image bakes it in at build time.

``HashingEmbedder`` is a deterministic stand-in with the same interface. It only captures
word overlap, not meaning, so it is used in tests rather than for real retrieval.
"""
from __future__ import annotations

import hashlib
import math
from typing import Protocol, Sequence

from app.core.rag import tokenize

EMBEDDING_DIM = 384  # must match the vector column in migration 0002
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class EmbeddingUnavailable(RuntimeError):
    """The embedding model could not be loaded (not installed, or download failed)."""


class FastEmbedEmbedder:
    """Local ONNX embedding model via ``fastembed``; loaded on first use."""

    dim = EMBEDDING_DIM

    def __init__(self, model: str = DEFAULT_MODEL, cache_dir: str | None = None) -> None:
        self.name = model
        self._cache_dir = cache_dir
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(model_name=self.name, cache_dir=self._cache_dir)
            except Exception as exc:  # import error, download failure, corrupt cache...
                raise EmbeddingUnavailable(f"Could not load embedding model {self.name}: {exc}") from exc
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return [vec.tolist() for vec in self._load().passage_embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        # bge models expect queries and passages to be encoded slightly differently
        return next(iter(self._load().query_embed(text))).tolist()


class HashingEmbedder:
    """Feature-hashed bag of words, L2-normalised. Deterministic; for tests."""

    name = "hashing"

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in tokenize(text):
            digest = hashlib.md5(token.encode()).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            vec[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
