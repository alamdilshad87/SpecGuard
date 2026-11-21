"""Keyword, vector and hybrid retrieval over a spec version's chunks.

* ``bm25``   - keyword ranking (in memory, see ``app.core.rag.BM25Index``)
* ``vector`` - cosine similarity of embeddings stored in ``retrieval_chunks``; on PostgreSQL
               this is a pgvector query using the HNSW index, elsewhere it is computed in Python
* ``hybrid`` - both lists fused with Reciprocal Rank Fusion

Vector search needs an embedding model. When none is configured or it fails to load,
requests degrade to BM25 and say so instead of erroring.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.core.embeddings import Embedder, EmbeddingUnavailable, FastEmbedEmbedder, cosine
from app.core.rag import BM25Index, Chunk, Hit, reciprocal_rank_fusion
from app.models import RetrievalChunk

Mode = Literal["bm25", "vector", "hybrid"]
CANDIDATES = 20  # how deep each retriever looks before fusion

log = logging.getLogger("specguard.retrieval")


@lru_cache(maxsize=1)
def _default_embedder() -> Embedder | None:
    if settings.embedding_provider == "none":
        return None
    return FastEmbedEmbedder(settings.embedding_model, settings.embedding_cache_dir or None)


def get_embedder() -> Embedder | None:
    """FastAPI dependency; tests override it with a deterministic embedder."""
    return _default_embedder()


def corpus_key(chunks: list[Chunk], model: str) -> str:
    digest = hashlib.sha256(model.encode())
    for c in chunks:
        digest.update(b"\0" + c.id.encode() + b"\0" + c.title.encode() + b"\0" + c.text.encode())
    return digest.hexdigest()


def ensure_index(db: Session, version_id: int, chunks: list[Chunk], embedder: Embedder) -> str:
    """Make sure ``retrieval_chunks`` holds exactly these chunks for the version; return the corpus key."""
    key = corpus_key(chunks, embedder.name)

    def indexed() -> int:
        return db.scalar(select(func.count()).select_from(RetrievalChunk)
                         .where(RetrievalChunk.spec_version_id == version_id,
                                RetrievalChunk.corpus_key == key)) or 0

    if indexed() == len(chunks):
        return key
    if db.get_bind().dialect.name == "postgresql":
        # Serialise concurrent first requests for the same version; released at commit.
        db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": version_id})
        if indexed() == len(chunks):
            db.commit()
            return key

    vectors = embedder.embed_documents([f"{c.title}\n{c.text}" for c in chunks])
    db.execute(delete(RetrievalChunk).where(RetrievalChunk.spec_version_id == version_id))
    db.add_all(
        RetrievalChunk(spec_version_id=version_id, corpus_key=key, chunk_key=c.id, source=c.source,
                       title=c.title, text=c.text, embedding=vec)
        for c, vec in zip(chunks, vectors)
    )
    db.commit()
    log.info("Indexed %d chunks for spec version %d with %s", len(chunks), version_id, embedder.name)
    return key


def _chunk(row: RetrievalChunk) -> Chunk:
    return Chunk(row.chunk_key, row.source, row.title, row.text)


def vector_search(db: Session, version_id: int, key: str, query: list[float], k: int) -> list[Hit]:
    scope = (RetrievalChunk.spec_version_id == version_id, RetrievalChunk.corpus_key == key)
    if db.get_bind().dialect.name == "postgresql":
        distance = RetrievalChunk.embedding.cosine_distance(query)
        rows = db.execute(select(RetrievalChunk, distance.label("d")).where(*scope).order_by(distance).limit(k))
        return [Hit(_chunk(row), 1.0 - float(d)) for row, d in rows]
    rows = db.scalars(select(RetrievalChunk).where(*scope)).all()
    scored = sorted(((cosine(query, list(r.embedding)), r) for r in rows), key=lambda x: x[0], reverse=True)
    return [Hit(_chunk(r), score) for score, r in scored[:k]]


@dataclass
class Retrieval:
    hits: list[Hit]
    mode: Mode  # the mode actually used
    note: str | None = None


def retrieve(db: Session, version_id: int, chunks: list[Chunk], bm25: BM25Index, question: str,
             k: int, mode: Mode, embedder: Embedder | None) -> Retrieval:
    if mode == "bm25":
        return Retrieval(bm25.search(question, k), "bm25")
    if embedder is None:
        return Retrieval(bm25.search(question, k), "bm25", "Vector search is disabled; used keyword search")
    try:
        key = ensure_index(db, version_id, chunks, embedder)
        dense = vector_search(db, version_id, key, embedder.embed_query(question),
                              k if mode == "vector" else CANDIDATES)
    except EmbeddingUnavailable as exc:
        log.warning("%s; falling back to BM25", exc)
        return Retrieval(bm25.search(question, k), "bm25", "Embedding model unavailable; used keyword search")
    if mode == "vector":
        return Retrieval(dense, "vector")
    return Retrieval(reciprocal_rank_fusion([bm25.search(question, CANDIDATES), dense], limit=k), "hybrid")
