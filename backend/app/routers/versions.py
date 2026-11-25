from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.diff import compare
from app.core.docs import generate_markdown
from app.core.parser import ParsedSpec, SpecError, parse_spec
from app.core.testgen import generate_tests
from app.database import get_db
from app.models import SpecVersion, TestRun
from app.schemas import DiffRequest, DocsOut, OperationOut, RunCreate, RunOut, VersionDetail

router = APIRouter(tags=["analysis"])


def _version_or_404(db: Session, version_id: int) -> SpecVersion:
    version = db.get(SpecVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Spec version not found")
    return version


def _parsed(version: SpecVersion) -> ParsedSpec:
    # Stored specs were validated on upload, so parsing here should not fail.
    return parse_spec(version.raw)


@router.get("/versions/{version_id}", response_model=VersionDetail)
def get_version(version_id: int, db: Session = Depends(get_db)) -> VersionDetail:
    version = _version_or_404(db, version_id)
    spec = _parsed(version)
    return VersionDetail(
        id=version.id, project_id=version.project_id, label=version.label, title=version.title,
        openapi=version.openapi, operation_count=version.operation_count, created_at=version.created_at,
        servers=spec.servers,
        operations=[OperationOut(key=o.key, operation_id=o.operation_id, summary=o.summary,
                                 tags=o.tags, deprecated=o.deprecated) for o in spec.operations],
    )


@router.delete("/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_version(version_id: int, db: Session = Depends(get_db)) -> None:
    db.delete(_version_or_404(db, version_id))
    db.commit()


@router.get("/versions/{version_id}/docs", response_model=DocsOut)
def get_docs(version_id: int, db: Session = Depends(get_db)) -> DocsOut:
    return DocsOut(content=generate_markdown(_parsed(_version_or_404(db, version_id))))


@router.get("/versions/{version_id}/tests")
def get_tests(version_id: int, db: Session = Depends(get_db)) -> list[dict]:
    return [case.to_dict() for case in generate_tests(_parsed(_version_or_404(db, version_id)))]


@router.post("/versions/{version_id}/runs", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
def create_run(version_id: int, payload: RunCreate, response: Response, db: Session = Depends(get_db)) -> TestRun:
    """Queue a test run. A background worker executes it; poll ``GET /runs/{id}`` for progress."""
    version = _version_or_404(db, version_id)
    run = TestRun(spec_version_id=version.id, base_url=str(payload.base_url).rstrip("/"),
                  categories=payload.categories, status="queued", results=[])
    db.add(run)
    db.commit()
    db.refresh(run)
    response.headers["Location"] = f"/runs/{run.id}"
    return run


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, db: Session = Depends(get_db)) -> TestRun:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test run not found")
    return run


@router.get("/versions/{version_id}/runs", response_model=list[RunOut])
def list_runs(version_id: int, db: Session = Depends(get_db)) -> list[TestRun]:
    _version_or_404(db, version_id)
    return list(db.scalars(select(TestRun).where(TestRun.spec_version_id == version_id)
                           .order_by(TestRun.created_at.desc())))


@router.get("/diff")
def diff_versions(from_id: int = Query(..., alias="from"), to_id: int = Query(..., alias="to"),
                  db: Session = Depends(get_db)) -> dict:
    old, new = _version_or_404(db, from_id), _version_or_404(db, to_id)
    result = compare(_parsed(old), _parsed(new))
    result.update(from_label=old.label, to_label=new.label)
    return result


@router.post("/analyze/diff")
def diff_raw(payload: DiffRequest) -> dict:
    """Stateless diff of two specs, handy for CI pipelines."""
    try:
        return compare(parse_spec(payload.old), parse_spec(payload.new))
    except SpecError as exc:
        raise HTTPException(422, str(exc))
