from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import insights, projects, versions

# The schema is managed by Alembic: run `python -m app.migrate` before starting the API
# (the Docker image does this on start-up).

app = FastAPI(
    title=settings.app_name,
    description="Analyze OpenAPI specs: docs, linting, breaking-change detection, generated API tests, "
                "code-vs-spec drift detection and grounded Q&A.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(versions.router)
app.include_router(insights.router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}
