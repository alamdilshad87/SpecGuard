"""Bring the database schema up to date: ``python -m app.migrate``.

Databases created before migrations existed (tables made by ``create_all``) have the
initial schema but no ``alembic_version`` table. Those are stamped as revision 0001 first,
so ``upgrade head`` only applies what came after instead of failing on existing tables.
"""
from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
INITIAL_REVISION = "0001"

log = logging.getLogger("specguard.migrate")


def register_vector_type(connection) -> None:
    """Let PostgreSQL reflection recognise pgvector columns (for autogenerate/compare)."""
    if connection.dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector
        connection.dialect.ischema_names["vector"] = Vector


def compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    """Alembic type-compare hook: SQLite has no vector type and reflects it as NUMERIC.

    Returning False means "no difference"; None falls back to Alembic's default comparison.
    """
    from pgvector.sqlalchemy import Vector

    if isinstance(metadata_type, Vector) and context.dialect.name == "sqlite":
        return False
    return None


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logging"] = False
    return config


def upgrade(url: str | None = None) -> None:
    url = url or settings.database_url
    config = alembic_config(url)
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    if "projects" in tables and "alembic_version" not in tables:
        log.info("Existing schema without migration history; stamping revision %s", INITIAL_REVISION)
        command.stamp(config, INITIAL_REVISION)
    command.upgrade(config, "head")
    log.info("Database schema is up to date")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    upgrade()
