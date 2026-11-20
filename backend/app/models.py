from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    versions: Mapped[list["SpecVersion"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="SpecVersion.created_at"
    )


class SpecVersion(Base):
    __tablename__ = "spec_versions"
    __table_args__ = (UniqueConstraint("project_id", "label", name="uq_project_label"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(300))
    openapi: Mapped[str] = mapped_column(String(20))
    operation_count: Mapped[int] = mapped_column(Integer)
    raw: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="versions")
    runs: Mapped[list["TestRun"]] = relationship(back_populates="spec_version", cascade="all, delete-orphan")
    scans: Mapped[list["CodeScan"]] = relationship(back_populates="spec_version", cascade="all, delete-orphan")


class TestRun(Base):
    __tablename__ = "test_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spec_version_id: Mapped[int] = mapped_column(ForeignKey("spec_versions.id", ondelete="CASCADE"), index=True)
    base_url: Mapped[str] = mapped_column(String(500))
    total: Mapped[int] = mapped_column(Integer)
    passed: Mapped[int] = mapped_column(Integer)
    results: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    spec_version: Mapped[SpecVersion] = relationship(back_populates="runs")


class CodeScan(Base):
    """Routes found in uploaded source code and how they compare with a spec version."""

    __tablename__ = "code_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spec_version_id: Mapped[int] = mapped_column(ForeignKey("spec_versions.id", ondelete="CASCADE"), index=True)
    files_scanned: Mapped[int] = mapped_column(Integer)
    in_sync: Mapped[bool] = mapped_column(Boolean)
    routes: Mapped[list] = mapped_column(JSON)
    report: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    spec_version: Mapped[SpecVersion] = relationship(back_populates="scans")
