"""Background worker that executes queued test runs: ``python -m app.worker``.

The ``test_runs`` table is the queue. A worker claims the oldest queued run with
``SELECT ... FOR UPDATE SKIP LOCKED``: the row is locked for the claiming transaction, and
other workers skip it instead of waiting, so any number of workers can poll the same table
without ever picking up the same run.

If a worker dies mid-run, its job stays ``running``. Each claim first requeues jobs that have
been running longer than ``worker_stale_after_seconds``, or fails them once they have used
``worker_max_attempts``.
"""
from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import and_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.core.parser import parse_spec
from app.core.runner import run_tests
from app.core.testgen import generate_tests
from app.models import SpecVersion, TestRun

log = logging.getLogger("specguard.worker")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def recover_stale(db: Session, stale_after: float, max_attempts: int) -> None:
    """Requeue runs orphaned by a crashed worker, or fail them after too many attempts."""
    stale = and_(TestRun.status == "running", TestRun.started_at < _now() - timedelta(seconds=stale_after))
    db.execute(update(TestRun).where(stale, TestRun.attempts < max_attempts)
               .values(status="queued", started_at=None))
    db.execute(update(TestRun).where(stale, TestRun.attempts >= max_attempts)
               .values(status="failed", finished_at=_now(),
                       error=f"Gave up after {max_attempts} attempts (worker stopped responding)"))
    db.commit()


def claim_next(db: Session, stale_after: float | None = None, max_attempts: int | None = None) -> TestRun | None:
    """Atomically take the oldest queued run and mark it running; ``None`` if the queue is empty."""
    recover_stale(db, settings.worker_stale_after_seconds if stale_after is None else stale_after,
                  settings.worker_max_attempts if max_attempts is None else max_attempts)
    run = db.scalars(
        select(TestRun).where(TestRun.status == "queued")
        .order_by(TestRun.created_at, TestRun.id).limit(1)
        .with_for_update(skip_locked=True)  # no-op on SQLite, which has a single writer anyway
    ).first()
    if run is None:
        db.commit()
        return None
    run.status = "running"
    run.started_at = _now()
    run.attempts += 1
    db.commit()  # releases the row lock; the status change now keeps other workers away
    return run


def execute(db: Session, run: TestRun, transport: httpx.BaseTransport | None = None) -> TestRun:
    """Generate and run the tests for a claimed run, then record the outcome."""
    try:
        version = db.get(SpecVersion, run.spec_version_id)
        if version is None:
            raise LookupError("Spec version was deleted")
        cases = generate_tests(parse_spec(version.raw))
        if run.categories:
            cases = [c for c in cases if c.category in run.categories]
        report = run_tests(cases, run.base_url, timeout=settings.runner_timeout_seconds, transport=transport)
        run.total, run.passed, run.results = report["total"], report["passed"], report["results"]
        run.status, run.error = "succeeded", None
    except Exception as exc:  # a broken spec or runner bug must not kill the worker
        log.exception("Run %s failed", run.id)
        run.status, run.error = "failed", f"{type(exc).__name__}: {exc}"
    run.finished_at = _now()
    db.commit()
    return run


def process_one(db: Session, transport: httpx.BaseTransport | None = None) -> TestRun | None:
    """Claim and execute one run. Returns the run, or ``None`` if nothing was queued."""
    run = claim_next(db)
    if run is None:
        return None
    log.info("Running test run %s against %s (attempt %s)", run.id, run.base_url, run.attempts)
    execute(db, run, transport)
    log.info("Test run %s %s: %s/%s passed", run.id, run.status, run.passed, run.total)
    return run


def main() -> None:
    from app.database import engine

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True
        log.info("Shutting down after the current run")

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("Worker started; polling every %ss", settings.worker_poll_seconds)

    while not stopping:
        try:
            with sessions() as db:
                did_work = process_one(db) is not None
        except Exception:  # e.g. database not reachable or not migrated yet
            log.exception("Worker loop error; retrying")
            did_work = False
        if not did_work:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
