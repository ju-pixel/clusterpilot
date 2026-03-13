"""SQLite job database.

Tracks every job ClusterPilot has submitted: status, paths, timestamps.
The daemon reads active jobs from here on each poll cycle.

DB file lives at ~/.local/share/clusterpilot/jobs.db.
All functions are async (aiosqlite).

Usage
-----
    import aiosqlite
    from clusterpilot.db import DB_PATH, init_db, insert_job, get_active_jobs

    async with aiosqlite.connect(DB_PATH) as db:
        await init_db(db)
        jobs = await get_active_jobs(db)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

DB_PATH = Path.home() / ".local" / "share" / "clusterpilot" / "jobs.db"

_CREATE_JOBS = """
CREATE TABLE IF NOT EXISTS jobs (
    row_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        TEXT    NOT NULL,
    job_name      TEXT    NOT NULL,
    cluster_name  TEXT    NOT NULL,
    host          TEXT    NOT NULL,
    user          TEXT    NOT NULL,
    account       TEXT    NOT NULL,
    partition     TEXT    NOT NULL,
    script_path   TEXT    NOT NULL,  -- absolute remote path to .sh script
    working_dir   TEXT    NOT NULL,  -- remote job directory ($scratch/job_name)
    local_dir     TEXT    NOT NULL,  -- local project directory
    status        TEXT    NOT NULL DEFAULT 'PENDING',
    submitted_at  REAL    NOT NULL,
    started_at    REAL,
    finished_at   REAL,
    walltime      TEXT    NOT NULL,  -- requested walltime, e.g. "08:00:00"
    log_path      TEXT,              -- remote stdout log path (found after start)
    synced        INTEGER NOT NULL DEFAULT 0,  -- 1 once results are downloaded
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    model_used    TEXT    NOT NULL DEFAULT '',
    UNIQUE(job_id, cluster_name)
)
"""

_CREATE_IDX = """
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)
"""


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class JobRecord:
    job_id: str
    job_name: str
    cluster_name: str
    host: str
    user: str
    account: str
    partition: str
    script_path: str
    working_dir: str
    local_dir: str
    walltime: str
    status: str = "PENDING"
    submitted_at: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None
    log_path: str | None = None
    synced: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    model_used: str = ""
    row_id: int | None = None

    def __post_init__(self) -> None:
        if not self.submitted_at:
            self.submitted_at = time.time()

    @property
    def is_terminal(self) -> bool:
        from clusterpilot.cluster.slurm import TERMINAL_STATES
        return self.status in TERMINAL_STATES

    @property
    def elapsed_seconds(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.finished_at or time.time()
        return end - self.started_at


# ── Schema ────────────────────────────────────────────────────────────────────

async def init_db(db: "aiosqlite.Connection") -> None:
    """Create tables and indexes if they don't exist. Safe to call repeatedly.

    Also migrates older databases by adding columns that were introduced
    after the initial schema.
    """
    await db.execute(_CREATE_JOBS)
    await db.execute(_CREATE_IDX)
    # Migration: add usage columns for databases created before this feature.
    for col, defn in (
        ("input_tokens",  "INTEGER NOT NULL DEFAULT 0"),
        ("output_tokens", "INTEGER NOT NULL DEFAULT 0"),
        ("model_used",    "TEXT NOT NULL DEFAULT ''"),
    ):
        try:
            await db.execute(f"ALTER TABLE jobs ADD COLUMN {col} {defn}")
        except Exception:
            pass  # Column already exists.
    await db.commit()


# ── Write operations ──────────────────────────────────────────────────────────

async def insert_job(db: "aiosqlite.Connection", job: JobRecord) -> int:
    """Insert a new job record. Returns the assigned row_id."""
    cur = await db.execute(
        """
        INSERT INTO jobs (
            job_id, job_name, cluster_name, host, user, account,
            partition, script_path, working_dir, local_dir, status,
            submitted_at, walltime, input_tokens, output_tokens, model_used
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job.job_id, job.job_name, job.cluster_name, job.host,
            job.user, job.account, job.partition, job.script_path,
            job.working_dir, job.local_dir, job.status,
            job.submitted_at, job.walltime,
            job.input_tokens, job.output_tokens, job.model_used,
        ),
    )
    await db.commit()
    assert cur.lastrowid is not None
    return cur.lastrowid


async def update_status(
    db: "aiosqlite.Connection",
    job_id: str,
    cluster_name: str,
    status: str,
    *,
    started_at: float | None = None,
    finished_at: float | None = None,
    log_path: str | None = None,
    synced: bool | None = None,
) -> None:
    """Update mutable fields for a job. Only non-None kwargs are written."""
    sets: list[str] = ["status = ?"]
    params: list[object] = [status]

    if started_at is not None:
        sets.append("started_at = ?")
        params.append(started_at)
    if finished_at is not None:
        sets.append("finished_at = ?")
        params.append(finished_at)
    if log_path is not None:
        sets.append("log_path = ?")
        params.append(log_path)
    if synced is not None:
        sets.append("synced = ?")
        params.append(1 if synced else 0)

    params.extend([job_id, cluster_name])
    await db.execute(
        f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = ? AND cluster_name = ?",
        params,
    )
    await db.commit()


async def delete_job(
    db: "aiosqlite.Connection",
    job_id: str,
    cluster_name: str,
) -> None:
    """Delete a job record from the database."""
    await db.execute(
        "DELETE FROM jobs WHERE job_id = ? AND cluster_name = ?",
        (job_id, cluster_name),
    )
    await db.commit()


# ── Read operations ───────────────────────────────────────────────────────────

async def get_job(
    db: "aiosqlite.Connection",
    job_id: str,
    cluster_name: str,
) -> JobRecord | None:
    """Return the JobRecord for this job, or None if not found."""
    async with db.execute(
        "SELECT * FROM jobs WHERE job_id = ? AND cluster_name = ?",
        (job_id, cluster_name),
    ) as cur:
        row = await cur.fetchone()
    return _row_to_record(row) if row else None


async def get_active_jobs(db: "aiosqlite.Connection") -> list[JobRecord]:
    """Return all jobs not yet in a terminal state, ordered by submission time."""
    from clusterpilot.cluster.slurm import TERMINAL_STATES
    placeholders = ",".join("?" * len(TERMINAL_STATES))
    async with db.execute(
        f"SELECT * FROM jobs WHERE status NOT IN ({placeholders}) "
        f"ORDER BY submitted_at DESC",
        list(TERMINAL_STATES),
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_record(r) for r in rows]


async def get_all_jobs(
    db: "aiosqlite.Connection",
    limit: int = 100,
) -> list[JobRecord]:
    """Return all jobs newest-first, up to limit."""
    async with db.execute(
        "SELECT * FROM jobs ORDER BY submitted_at DESC LIMIT ?",
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_record(r) for r in rows]


async def get_total_usage(
    db: "aiosqlite.Connection",
) -> tuple[int, int]:
    """Return (total_input_tokens, total_output_tokens) across all jobs."""
    async with db.execute(
        "SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0) FROM jobs"
    ) as cur:
        row = await cur.fetchone()
    return (row[0], row[1]) if row else (0, 0)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_record(row: tuple) -> JobRecord:  # type: ignore[type-arg]
    (
        row_id, job_id, job_name, cluster_name, host, user, account,
        partition, script_path, working_dir, local_dir, status,
        submitted_at, started_at, finished_at, walltime, log_path, synced,
        input_tokens, output_tokens, model_used,
    ) = row
    return JobRecord(
        row_id=row_id,
        job_id=job_id,
        job_name=job_name,
        cluster_name=cluster_name,
        host=host,
        user=user,
        account=account,
        partition=partition,
        script_path=script_path,
        working_dir=working_dir,
        local_dir=local_dir,
        status=status,
        submitted_at=submitted_at,
        started_at=started_at,
        finished_at=finished_at,
        walltime=walltime,
        log_path=log_path,
        synced=bool(synced),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model_used=model_used,
    )
