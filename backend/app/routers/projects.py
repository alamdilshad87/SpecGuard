from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.parser import SpecError, parse_spec
from app.database import get_db
from app.models import Project, SpecVersion
from app.schemas import ProjectCreate, ProjectOut, VersionCreate, VersionSummary

router = APIRouter(prefix="/projects", tags=["projects"])

MAX_SPEC_BYTES = 5 * 1024 * 1024


def get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    project = Project(name=payload.name.strip())
    db.add(project)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A project with this name already exists")
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.created_at.desc())))


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)) -> Project:
    return get_project_or_404(db, project_id)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Session = Depends(get_db)) -> None:
    db.delete(get_project_or_404(db, project_id))
    db.commit()


def _store_version(db: Session, project: Project, label: str, content: str) -> SpecVersion:
    try:
        parsed = parse_spec(content)
    except SpecError as exc:
        raise HTTPException(422, str(exc))
    version = SpecVersion(
        project_id=project.id,
        label=label.strip(),
        title=parsed.title,
        openapi=parsed.openapi,
        operation_count=len(parsed.operations),
        raw=content,
    )
    db.add(version)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"Version '{label}' already exists in this project")
    db.refresh(version)
    return version


@router.post("/{project_id}/versions", response_model=VersionSummary, status_code=status.HTTP_201_CREATED)
def add_version(project_id: int, payload: VersionCreate, db: Session = Depends(get_db)) -> SpecVersion:
    return _store_version(db, get_project_or_404(db, project_id), payload.label, payload.content)


@router.post("/{project_id}/versions/upload", response_model=VersionSummary, status_code=status.HTTP_201_CREATED)
async def upload_version(project_id: int, label: str = Form(...), file: UploadFile = File(...),
                         db: Session = Depends(get_db)) -> SpecVersion:
    project = get_project_or_404(db, project_id)
    data = await file.read(MAX_SPEC_BYTES + 1)
    if len(data) > MAX_SPEC_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Spec file is larger than 5 MB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(422, "Spec file must be UTF-8 text")
    return _store_version(db, project, label, text)
