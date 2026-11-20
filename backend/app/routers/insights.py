"""Spec linting, code-vs-spec drift scans and question answering."""
import io
import zipfile
from functools import lru_cache

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.codescan import Route, compare_with_spec, is_scannable, scan_sources
from app.core.lint import lint
from app.core.parser import SpecError, parse_spec
from app.core.rag import BM25Index, LLMConfig, answer, chunks_from_routes, chunks_from_spec
from app.database import get_db
from app.models import CodeScan, SpecVersion
from app.routers.versions import _parsed, _version_or_404
from app.schemas import AskOut, AskRequest, LintRequest, ScanOut

router = APIRouter(tags=["insights"])

MAX_SOURCE_BYTES = 10 * 1024 * 1024  # total uncompressed source accepted per scan
MAX_SOURCE_FILES = 2000


# ---------------------------------------------------------------- lint

@router.post("/analyze/lint")
def lint_raw(payload: LintRequest) -> dict:
    """Stateless lint of a raw spec."""
    try:
        return lint(payload.content)
    except SpecError as exc:
        raise HTTPException(422, str(exc))


@router.get("/versions/{version_id}/lint")
def lint_version(version_id: int, db: Session = Depends(get_db)) -> dict:
    return lint(_version_or_404(db, version_id).raw)


# ---------------------------------------------------------------- drift scan

class _Budget:
    """Caps how much uploaded source a single scan may read."""

    def __init__(self) -> None:
        self.bytes = 0
        self.files = 0

    def take(self, size: int) -> None:
        self.bytes += size
        self.files += 1
        if self.bytes > MAX_SOURCE_BYTES or self.files > MAX_SOURCE_FILES:
            raise HTTPException(413,
                                f"Source upload exceeds {MAX_SOURCE_BYTES // (1024 * 1024)} MB or {MAX_SOURCE_FILES} files")


def _decode(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _extract_zip(data: bytes, budget: _Budget) -> dict[str, str]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(422, "Uploaded .zip file is not a valid archive")
    files: dict[str, str] = {}
    for info in archive.infolist():
        if info.is_dir() or not is_scannable(info.filename):
            continue
        budget.take(info.file_size)  # declared size, checked before decompressing
        text = _decode(archive.read(info))
        if text is not None:
            files[info.filename] = text
    return files


async def _read_sources(uploads: list[UploadFile]) -> dict[str, str]:
    budget = _Budget()
    files: dict[str, str] = {}
    for upload in uploads:
        name = upload.filename or "upload"
        data = await upload.read(MAX_SOURCE_BYTES + 1)
        if name.lower().endswith(".zip"):
            if len(data) > MAX_SOURCE_BYTES:
                budget.take(len(data))
            files.update(_extract_zip(data, budget))
        elif is_scannable(name):
            budget.take(len(data))
            text = _decode(data)
            if text is not None:
                files[name] = text
    return files


@router.post("/versions/{version_id}/scans", response_model=ScanOut, status_code=status.HTTP_201_CREATED)
async def create_scan(version_id: int, files: list[UploadFile] = File(..., description="Source files or a .zip"),
                      db: Session = Depends(get_db)) -> CodeScan:
    """Find routes in uploaded source code and compare them with this spec version."""
    version = _version_or_404(db, version_id)
    sources = await _read_sources(files)
    if not sources:
        raise HTTPException(422, "No supported source files found (.py, .js, .ts, .mjs, .cjs or a .zip of them)")
    routes = scan_sources(sources)
    report = compare_with_spec(routes, _parsed(version))
    scan = CodeScan(spec_version_id=version.id, files_scanned=len(sources), in_sync=report["in_sync"],
                    routes=[r.to_dict() for r in routes], report=report)
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


@router.get("/versions/{version_id}/scans", response_model=list[ScanOut])
def list_scans(version_id: int, db: Session = Depends(get_db)) -> list[CodeScan]:
    _version_or_404(db, version_id)
    return list(db.scalars(select(CodeScan).where(CodeScan.spec_version_id == version_id)
                           .order_by(CodeScan.created_at.desc(), CodeScan.id.desc())))


# ---------------------------------------------------------------- ask

def _latest_scan(db: Session, version_id: int) -> CodeScan | None:
    return db.scalars(select(CodeScan).where(CodeScan.spec_version_id == version_id)
                      .order_by(CodeScan.created_at.desc(), CodeScan.id.desc()).limit(1)).first()


@lru_cache(maxsize=64)
def _index(raw: str, routes: tuple[tuple, ...]) -> BM25Index:
    """Build (and cache) the retrieval index for a spec plus documented routes from its latest scan."""
    chunks = chunks_from_spec(parse_spec(raw))
    chunks += chunks_from_routes([Route(*r) for r in routes])
    return BM25Index(chunks)


def _llm_config() -> LLMConfig:
    return LLMConfig(base_url=settings.llm_base_url, api_key=settings.llm_api_key,
                     model=settings.llm_model, timeout=settings.llm_timeout_seconds)


@router.post("/versions/{version_id}/ask", response_model=AskOut)
def ask(version_id: int, payload: AskRequest, db: Session = Depends(get_db)) -> dict:
    """Answer a question from this spec version and, if scanned, its source code docstrings."""
    version: SpecVersion = _version_or_404(db, version_id)
    scan = _latest_scan(db, version_id)
    routes = tuple(
        (r["method"], r["path"], r["file"], r["line"], r.get("handler", ""), r["doc"])
        for r in (scan.routes if scan else []) if r.get("doc")
    )
    index = _index(version.raw, routes)
    return answer(index, payload.question, k=payload.k, llm=_llm_config() if payload.use_llm else None)
