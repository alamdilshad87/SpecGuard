"""Retrieval chunks with pgvector embeddings for semantic search.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 384  # BAAI/bge-small-en-v1.5; fixed so the HNSW index can be built


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "retrieval_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("spec_version_id", sa.Integer(), sa.ForeignKey("spec_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("corpus_key", sa.String(length=64), nullable=False),
        sa.Column("chunk_key", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    )
    op.create_index("ix_retrieval_chunks_version_corpus", "retrieval_chunks", ["spec_version_id", "corpus_key"])
    # Approximate nearest-neighbour index for cosine distance (PostgreSQL only; a plain
    # index elsewhere, where search falls back to exact comparison in Python).
    op.create_index(
        "ix_retrieval_chunks_embedding_hnsw", "retrieval_chunks", ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_retrieval_chunks_embedding_hnsw", table_name="retrieval_chunks")
    op.drop_index("ix_retrieval_chunks_version_corpus", table_name="retrieval_chunks")
    op.drop_table("retrieval_chunks")
    # The extension is left installed: other database objects may use it.
