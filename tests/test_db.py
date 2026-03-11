"""Tests for db.py — SQLite job database operations."""
from __future__ import annotations

import time

import aiosqlite
import pytest

from clusterpilot.db import (
    JobRecord,
    get_active_jobs,
    get_all_jobs,
    get_job,
    init_db,
    insert_job,
    update_status,
)


def _make_job(**kwargs) -> JobRecord:
    defaults = dict(
        job_id="12345",
        job_name="test_job",
        cluster_name="grex",
        host="yak.hpc.umanitoba.ca",
        user="juliaf",
        account="def-stamps",
        partition="stamps",
        script_path="/home/juliaf/clusterpilot_jobs/test_job/job.sh",
        working_dir="/home/juliaf/clusterpilot_jobs/test_job",
        local_dir="/Users/juliaf/projects/myproject",
        walltime="08:00:00",
    )
    defaults.update(kwargs)
    return JobRecord(**defaults)


@pytest.fixture
async def db():
    """Yield a fresh in-memory database with schema initialised."""
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        yield conn


# ── init_db ───────────────────────────────────────────────────────────────────

async def test_init_db_idempotent(db):
    """Calling init_db twice should not raise."""
    await init_db(db)  # second call


# ── insert_job / get_job round-trip ──────────────────────────────────────────

async def test_insert_and_get_job(db):
    job = _make_job()
    row_id = await insert_job(db, job)
    assert isinstance(row_id, int)
    assert row_id > 0

    fetched = await get_job(db, "12345", "grex")
    assert fetched is not None
    assert fetched.job_id == "12345"
    assert fetched.job_name == "test_job"
    assert fetched.partition == "stamps"
    assert fetched.status == "PENDING"
    assert fetched.row_id == row_id


async def test_get_job_returns_none_when_missing(db):
    result = await get_job(db, "nonexistent", "grex")
    assert result is None


async def test_get_job_distinguishes_clusters(db):
    job_grex = _make_job(job_id="1", cluster_name="grex")
    job_cedar = _make_job(job_id="1", cluster_name="cedar")
    await insert_job(db, job_grex)
    await insert_job(db, job_cedar)

    result = await get_job(db, "1", "cedar")
    assert result is not None
    assert result.cluster_name == "cedar"


# ── update_status ─────────────────────────────────────────────────────────────

async def test_update_status_changes_state(db):
    await insert_job(db, _make_job())
    await update_status(db, "12345", "grex", "RUNNING", started_at=time.time())

    fetched = await get_job(db, "12345", "grex")
    assert fetched is not None
    assert fetched.status == "RUNNING"
    assert fetched.started_at is not None


async def test_update_status_sets_finished_at(db):
    await insert_job(db, _make_job())
    t = time.time()
    await update_status(db, "12345", "grex", "COMPLETED", finished_at=t)

    fetched = await get_job(db, "12345", "grex")
    assert fetched.status == "COMPLETED"
    assert fetched.finished_at == pytest.approx(t)


async def test_update_status_sets_log_path(db):
    await insert_job(db, _make_job())
    await update_status(
        db, "12345", "grex", "RUNNING", log_path="/home/juliaf/test_job-12345.out"
    )
    fetched = await get_job(db, "12345", "grex")
    assert fetched.log_path == "/home/juliaf/test_job-12345.out"


async def test_update_status_sets_synced(db):
    await insert_job(db, _make_job())
    await update_status(db, "12345", "grex", "COMPLETED", synced=True)
    fetched = await get_job(db, "12345", "grex")
    assert fetched.synced is True


# ── get_active_jobs ───────────────────────────────────────────────────────────

async def test_get_active_jobs_excludes_terminal(db):
    pending = _make_job(job_id="1", status="PENDING")
    running = _make_job(job_id="2", status="RUNNING")
    completed = _make_job(job_id="3", status="COMPLETED")
    failed = _make_job(job_id="4", status="FAILED")

    for job in (pending, running, completed, failed):
        await insert_job(db, job)

    active = await get_active_jobs(db)
    active_ids = {j.job_id for j in active}
    assert "1" in active_ids
    assert "2" in active_ids
    assert "3" not in active_ids
    assert "4" not in active_ids


async def test_get_active_jobs_empty_when_all_terminal(db):
    for i, status in enumerate(("COMPLETED", "FAILED", "CANCELLED")):
        await insert_job(db, _make_job(job_id=str(i), status=status))
    assert await get_active_jobs(db) == []


# ── get_all_jobs ──────────────────────────────────────────────────────────────

async def test_get_all_jobs_respects_limit(db):
    for i in range(5):
        await insert_job(db, _make_job(job_id=str(i)))
    result = await get_all_jobs(db, limit=3)
    assert len(result) == 3


async def test_get_all_jobs_newest_first(db):
    # Use truthy submitted_at values — 0.0 is falsy and triggers __post_init__.
    for i in range(3):
        job = _make_job(job_id=str(i), submitted_at=1000.0 + i)
        await insert_job(db, job)
    result = await get_all_jobs(db)
    assert result[0].job_id == "2"  # highest submitted_at first


# ── JobRecord helpers ─────────────────────────────────────────────────────────

class TestJobRecord:
    def test_submitted_at_auto_set(self):
        before = time.time()
        job = _make_job()
        after = time.time()
        assert before <= job.submitted_at <= after

    def test_is_terminal_completed(self):
        job = _make_job(status="COMPLETED")
        assert job.is_terminal is True

    def test_is_terminal_failed(self):
        assert _make_job(status="FAILED").is_terminal is True

    def test_is_terminal_pending(self):
        assert _make_job(status="PENDING").is_terminal is False

    def test_is_terminal_running(self):
        assert _make_job(status="RUNNING").is_terminal is False

    def test_elapsed_seconds_none_before_start(self):
        job = _make_job()
        job.started_at = None
        assert job.elapsed_seconds is None

    def test_elapsed_seconds_after_finish(self):
        job = _make_job()
        t = time.time()
        job.started_at = t - 100
        job.finished_at = t
        assert job.elapsed_seconds == pytest.approx(100, abs=1)

    def test_elapsed_seconds_ongoing(self):
        job = _make_job()
        job.started_at = time.time() - 60
        job.finished_at = None
        assert job.elapsed_seconds is not None
        assert job.elapsed_seconds >= 60
