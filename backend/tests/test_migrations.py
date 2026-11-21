"""Migrations must build exactly the schema the models describe, on SQLite and PostgreSQL.

Set SPECGUARD_TEST_POSTGRES_URL (a throwaway database) to also run against PostgreSQL;
CI does this with a pgvector/pgvector service container.
"""
import os

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app import models  # noqa: F401
from app.database import Base
from app.migrate import alembic_config, compare_type, register_vector_type, upgrade

LEGACY_TABLES = ("projects", "spec_versions", "test_runs", "code_scans")  # schema before migrations
TABLES = {*LEGACY_TABLES, "retrieval_chunks"}
POSTGRES_URL = os.environ.get("SPECGUARD_TEST_POSTGRES_URL")


@pytest.fixture(params=["sqlite"] + (["postgres"] if POSTGRES_URL else []))
def db_url(request, tmp_path):
    if request.param == "sqlite":
        yield f"sqlite:///{tmp_path / 'migrations.db'}"
        return
    command.downgrade(alembic_config(POSTGRES_URL), "base")  # start clean
    engine = create_engine(POSTGRES_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()
    yield POSTGRES_URL
    command.downgrade(alembic_config(POSTGRES_URL), "base")


def _schema_diff(url: str) -> list:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            register_vector_type(conn)
            ctx = MigrationContext.configure(conn, opts={"compare_type": compare_type})
            return compare_metadata(ctx, Base.metadata)
    finally:
        engine.dispose()


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_matches_models_and_downgrade_removes_everything(db_url):
    upgrade(db_url)
    assert TABLES <= _tables(db_url)
    assert _schema_diff(db_url) == [], "models changed without a migration; run `alembic revision --autogenerate`"

    command.downgrade(alembic_config(db_url), "base")
    assert not TABLES & _tables(db_url)


def test_legacy_database_is_stamped_and_keeps_data(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(url)
    # How the schema was created before migrations existed (only the original tables)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in LEGACY_TABLES])
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO projects (name, created_at) VALUES ('Kept', CURRENT_TIMESTAMP)"))

    upgrade(url)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() is not None
        assert conn.execute(text("SELECT name FROM projects")).scalar() == "Kept"
    engine.dispose()
