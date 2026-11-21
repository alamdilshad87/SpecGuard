import os
from pathlib import Path

import pytest

# Use an in-memory SQLite database for tests; must be set before the app is imported.
os.environ.setdefault("SPECGUARD_DATABASE_URL", "sqlite://")
# Never download an embedding model in tests; the client fixture injects a deterministic one.
os.environ.setdefault("SPECGUARD_EMBEDDING_PROVIDER", "none")

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture
def spec_v1() -> str:
    return (EXAMPLES / "bookstore-v1.yaml").read_text()


@pytest.fixture
def spec_v2() -> str:
    return (EXAMPLES / "bookstore-v2.yaml").read_text()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from sqlalchemy import create_engine

    from app.database import Base, get_db
    from app.core.embeddings import HashingEmbedder
    from app.main import app
    from app.services.retrieval import get_embedder

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_embedder] = lambda: HashingEmbedder()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
