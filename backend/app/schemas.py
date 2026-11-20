from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class VersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    title: str
    openapi: str
    operation_count: int
    created_at: datetime


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    versions: list[VersionSummary] = []


class VersionCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100, description="e.g. v1, 2.0.0, main")
    content: str = Field(min_length=1, description="OpenAPI 3.x document as JSON or YAML text")


class OperationOut(BaseModel):
    key: str
    operation_id: str
    summary: str
    tags: list[str]
    deprecated: bool


class VersionDetail(VersionSummary):
    project_id: int
    servers: list[str]
    operations: list[OperationOut]


class DocsOut(BaseModel):
    format: Literal["markdown"] = "markdown"
    content: str


class RunCreate(BaseModel):
    base_url: HttpUrl
    categories: list[Literal["positive", "negative", "edge"]] | None = None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    spec_version_id: int
    base_url: str
    total: int
    passed: int
    created_at: datetime
    results: list[dict[str, Any]]


class DiffRequest(BaseModel):
    old: str = Field(min_length=1)
    new: str = Field(min_length=1)


class LintRequest(BaseModel):
    content: str = Field(min_length=1, description="OpenAPI 3.x document as JSON or YAML text")


class ScanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    spec_version_id: int
    files_scanned: int
    in_sync: bool
    created_at: datetime
    report: dict[str, Any]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=4, ge=1, le=20, description="How many chunks to retrieve")
    use_llm: bool = True


class AskSource(BaseModel):
    id: str
    title: str
    source: Literal["operation", "code"]
    score: float


class AskOut(BaseModel):
    answer: str
    mode: Literal["llm", "extractive", "none"]
    sources: list[AskSource]
