"""Vector index and hybrid retrieval, on SQLite and (when configured) PostgreSQL + pgvector."""
import os

import pytest
from alembic import command
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.embeddings import EmbeddingUnavailable, HashingEmbedder
from app.core.parser import parse_spec
from app.core.rag import BM25Index, chunks_from_spec
from app.migrate import alembic_config, upgrade
from app.models import Project, RetrievalChunk, SpecVersion
from app.services.retrieval import ensure_index, retrieve, vector_search

POSTGRES_URL = os.environ.get("SPECGUARD_TEST_POSTGRES_URL")


@pytest.fixture(params=["sqlite"] + (["postgres"] if POSTGRES_URL else []))
def db(request, tmp_path, spec_v1):
    url = f"sqlite:///{tmp_path / 'retrieval.db'}" if request.param == "sqlite" else POSTGRES_URL
    if request.param == "postgres":
        command.downgrade(alembic_config(url), "base")
    upgrade(url)
    engine = create_engine(url)
    session = Session(engine, expire_on_commit=False)
    project = Project(name="Bookstore")
    session.add(project)
    session.flush()
    session.add(SpecVersion(project_id=project.id, label="v1", title="Bookstore", openapi="3.0.3",
                            operation_count=4, raw=spec_v1))
    session.commit()
    yield session
    session.close()
    engine.dispose()
    if request.param == "postgres":
        command.downgrade(alembic_config(url), "base")


@pytest.fixture
def chunks(spec_v1):
    return chunks_from_spec(parse_spec(spec_v1))


def _version_id(db: Session) -> int:
    return db.scalar(select(SpecVersion.id))


def _rows(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(RetrievalChunk))


class CountingEmbedder(HashingEmbedder):
    def __init__(self):
        super().__init__()
        self.document_calls = 0

    def embed_documents(self, texts):
        self.document_calls += 1
        return super().embed_documents(texts)


def test_index_is_built_once_and_rebuilt_when_chunks_change(db, chunks):
    embedder, version = CountingEmbedder(), _version_id(db)

    key = ensure_index(db, version, chunks, embedder)
    assert ensure_index(db, version, chunks, embedder) == key
    assert embedder.document_calls == 1 and _rows(db) == len(chunks)

    changed = chunks[:-1]
    assert ensure_index(db, version, changed, embedder) != key
    assert embedder.document_calls == 2 and _rows(db) == len(changed)  # old rows replaced


def test_vector_search_ranks_by_cosine_similarity(db, chunks):
    embedder, version = HashingEmbedder(), _version_id(db)
    key = ensure_index(db, version, chunks, embedder)
    target = next(c for c in chunks if c.id == "op:DELETE /books/{bookId}")

    hits = vector_search(db, version, key, embedder.embed_query(f"{target.title}\n{target.text}"), k=3)

    assert hits[0].chunk.id == target.id
    assert hits[0].score == pytest.approx(1.0, abs=1e-4)
    assert len(hits) == 3 and hits[0].score >= hits[1].score >= hits[2].score


@pytest.mark.parametrize("mode", ["bm25", "vector", "hybrid"])
def test_retrieve_modes(db, chunks, mode):
    found = retrieve(db, _version_id(db), chunks, BM25Index(chunks), "delete a book", 3, mode, HashingEmbedder())
    assert found.mode == mode and found.note is None
    assert found.hits[0].chunk.id == "op:DELETE /books/{bookId}"


def test_retrieve_falls_back_to_bm25(db, chunks):
    class Broken(HashingEmbedder):
        def embed_documents(self, texts):
            raise EmbeddingUnavailable("model download failed")

    bm25 = BM25Index(chunks)
    disabled = retrieve(db, _version_id(db), chunks, bm25, "delete a book", 3, "hybrid", None)
    broken = retrieve(db, _version_id(db), chunks, bm25, "delete a book", 3, "vector", Broken())

    assert (disabled.mode, broken.mode) == ("bm25", "bm25")
    assert "disabled" in disabled.note and "unavailable" in broken.note
    assert broken.hits[0].chunk.id == "op:DELETE /books/{bookId}"
