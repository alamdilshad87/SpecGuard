"""The test-run queue: API enqueues, worker claims and executes (SQLite and PostgreSQL)."""
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from alembic import command
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.migrate import alembic_config, upgrade
from app.models import Project, SpecVersion, TestRun
from app.worker import claim_next, process_one
from tests.test_testgen_runner import _fake_bookstore

POSTGRES_URL = os.environ.get("SPECGUARD_TEST_POSTGRES_URL")
BOOKSTORE = httpx.MockTransport(_fake_bookstore)


@pytest.fixture(params=["sqlite"] + (["postgres"] if POSTGRES_URL else []))
def db_url(request, tmp_path, spec_v1):
    url = f"sqlite:///{tmp_path / 'queue.db'}" if request.param == "sqlite" else POSTGRES_URL
    if request.param == "postgres":
        command.downgrade(alembic_config(url), "base")
    upgrade(url)
    engine = create_engine(url)
    with Session(engine) as s:
        project = Project(name="Bookstore")
        s.add(project)
        s.flush()
        s.add(SpecVersion(project_id=project.id, label="v1", title="Bookstore", openapi="3.0.3",
                          operation_count=4, raw=spec_v1))
        s.commit()
    engine.dispose()
    yield url
    if request.param == "postgres":
        command.downgrade(alembic_config(url), "base")


@pytest.fixture
def db(db_url):
    engine = create_engine(db_url)
    session = Session(engine, expire_on_commit=False)
    yield session
    session.close()
    engine.dispose()


def _enqueue(db: Session, **fields) -> TestRun:
    version_id = db.scalar(select(SpecVersion.id))
    run = TestRun(spec_version_id=version_id, base_url="http://bookstore.test", status="queued", results=[], **fields)
    db.add(run)
    db.commit()
    return run


def test_worker_executes_queued_runs_in_order(db):
    first, second = _enqueue(db), _enqueue(db, categories=["positive"])

    done = process_one(db, BOOKSTORE)
    assert done.id == first.id
    assert (done.status, done.attempts, done.error) == ("succeeded", 1, None)
    assert done.total > 10 and done.passed == done.total
    assert done.started_at is not None and done.finished_at is not None

    filtered = process_one(db, BOOKSTORE)
    assert filtered.id == second.id
    assert {r["category"] for r in filtered.results} == {"positive"}

    assert process_one(db, BOOKSTORE) is None  # queue drained


def test_broken_spec_fails_the_run_not_the_worker(db):
    db.get(SpecVersion, db.scalar(select(SpecVersion.id))).raw = "not: an openapi document"
    db.commit()
    run = _enqueue(db)

    done = process_one(db, BOOKSTORE)

    assert done.id == run.id and done.status == "failed"
    assert done.error.startswith("SpecError")


def test_orphaned_runs_are_retried_then_given_up(db):
    long_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    orphan = _enqueue(db)
    orphan.status, orphan.started_at, orphan.attempts = "running", long_ago, 1
    exhausted = _enqueue(db)
    exhausted.status, exhausted.started_at, exhausted.attempts = "running", long_ago, 3
    db.commit()

    claimed = claim_next(db, stale_after=60, max_attempts=3)

    assert claimed.id == orphan.id and claimed.attempts == 2 and claimed.status == "running"
    db.refresh(exhausted)
    assert exhausted.status == "failed" and "Gave up after 3 attempts" in exhausted.error


def test_fresh_running_jobs_are_left_alone(db):
    busy = _enqueue(db)
    busy.status, busy.started_at, busy.attempts = "running", datetime.now(timezone.utc), 1
    db.commit()

    assert claim_next(db, stale_after=600, max_attempts=3) is None
    db.refresh(busy)
    assert busy.status == "running" and busy.attempts == 1


def test_concurrent_workers_never_claim_the_same_run(db_url):
    if db_url.startswith("sqlite"):
        pytest.skip("SKIP LOCKED needs PostgreSQL (set SPECGUARD_TEST_POSTGRES_URL)")
    engine = create_engine(db_url)
    with Session(engine, expire_on_commit=False) as setup:
        first, second = _enqueue(setup), _enqueue(setup)

    worker_a, worker_b = Session(engine), Session(engine, expire_on_commit=False)
    try:
        # Worker A is mid-claim: it holds the row lock on the oldest queued run.
        locked = worker_a.scalars(select(TestRun).where(TestRun.status == "queued")
                                  .order_by(TestRun.id).limit(1).with_for_update()).one()
        assert locked.id == first.id

        # Worker B skips the locked row instead of blocking, and takes the next one.
        claimed = claim_next(worker_b)
        assert claimed.id == second.id
    finally:
        worker_a.rollback()
        worker_a.close()
        worker_b.close()
        engine.dispose()


def test_api_queues_runs_and_reports_status(client, spec_v1):
    project = client.post("/projects", json={"name": "Queue"}).json()
    version = client.post(f"/projects/{project['id']}/versions", json={"label": "v1", "content": spec_v1}).json()

    response = client.post(f"/versions/{version['id']}/runs",
                           json={"base_url": "http://localhost:9000", "categories": ["edge"]})

    assert response.status_code == 202
    run = response.json()
    assert (run["status"], run["attempts"], run["categories"], run["results"]) == ("queued", 0, ["edge"], [])
    assert response.headers["location"] == f"/runs/{run['id']}"
    assert client.get(f"/runs/{run['id']}").json()["status"] == "queued"
    assert [r["id"] for r in client.get(f"/versions/{version['id']}/runs").json()] == [run["id"]]
    assert client.get("/runs/9999").status_code == 404
