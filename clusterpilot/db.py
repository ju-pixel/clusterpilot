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
from typing import TYPE_CHECKING

from clusterpilot import paths

if TYPE_CHECKING:
    import aiosqlite

    from clusterpilot.cluster.slurm import JobAccounting, JobAllocation

# Resolved once at import. Set CLUSTERPILOT_HOME to relocate this, the config
# file, the probe cache and the systemd unit together (see paths.py).
DB_PATH = paths.db_path()

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
    synced          INTEGER NOT NULL DEFAULT 0,  -- 1 once results are downloaded
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    model_used      TEXT    NOT NULL DEFAULT '',
    remote_cleaned  INTEGER NOT NULL DEFAULT 0,  -- 1 once remote working dir deleted
    array_spec      TEXT    NOT NULL DEFAULT '',  -- e.g. "0-9" or "1-100%5"; empty for non-array jobs
    status_detail   TEXT    NOT NULL DEFAULT '',  -- per-task breakdown, e.g. "5R/27PD"
    efficiency      TEXT    NOT NULL DEFAULT '',  -- seff summary, e.g. "CPU 12%, mem 6% of 16 GB"
    -- What sacct says the scheduler reserved. NULL means "not reported",
    -- which is not zero: a usage report must skip these rows, not add them up.
    alloc_cpus      INTEGER,           -- CPUs per array task
    alloc_gpus      INTEGER,           -- GPUs per array task
    alloc_nodes     INTEGER,           -- nodes per array task
    runtime_seconds INTEGER,           -- longest task, so the job's wall duration
    core_seconds    REAL,              -- sum of cpus x elapsed over every task
    gpu_seconds     REAL,              -- sum of gpus x elapsed over every task
    exit_code       TEXT    NOT NULL DEFAULT '',  -- worst task's "<exit>:<signal>"
    alloc_billing   INTEGER,           -- SLURM billing weight per task
    billing_seconds REAL,              -- sum of billing x elapsed over every task
    -- How the figures above were arrived at: 'sacct' when SLURM accounting
    -- answered, 'measured' when ClusterPilot integrated the running task
    -- count over its own poll cycles, empty when neither has happened. A
    -- usage report must never present 'measured' as an accounting record.
    accounting_source TEXT  NOT NULL DEFAULT '',
    measured_at     REAL,              -- poll time the running total reaches
    -- How many times a results download has been tried. Non-zero means one
    -- was attempted, which is what separates "the rsync failed" from "this
    -- job never wanted results" (issue #48).
    sync_attempts   INTEGER NOT NULL DEFAULT 0,
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
    remote_cleaned: bool = False
    array_spec: str = ""
    status_detail: str = ""   # per-task breakdown for arrays, e.g. "5R/27PD"
    efficiency: str = ""      # seff summary, e.g. "CPU 12%, mem 6% of 16 GB"
    # Accounting, from sacct once the job is finished. None means sacct did
    # not report it, which a usage report must treat as unknown, not zero.
    alloc_cpus: int | None = None
    alloc_gpus: int | None = None
    alloc_nodes: int | None = None
    runtime_seconds: int | None = None
    core_seconds: float | None = None
    gpu_seconds: float | None = None
    exit_code: str = ""
    alloc_billing: int | None = None
    billing_seconds: float | None = None
    accounting_source: str = ""   # 'sacct', 'measured', or "" for neither
    measured_at: float | None = None
    sync_attempts: int = 0        # results downloads tried; 0 means none was
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



_CREATE_GENERATIONS = """
CREATE TABLE IF NOT EXISTS generations (
    row_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at  REAL    NOT NULL,
    cluster_name  TEXT    NOT NULL DEFAULT '',
    model         TEXT    NOT NULL DEFAULT '',
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    -- 1 for the rows written once from the jobs table when this table was
    -- introduced, so an upgrade does not appear to wipe the running total.
    -- The seed is guarded on these rows rather than on the table being
    -- empty, so a real generation landing first cannot block it.
    seeded        INTEGER NOT NULL DEFAULT 0
)
"""

# ── Schema ────────────────────────────────────────────────────────────────────

async def init_db(db: "aiosqlite.Connection") -> None:
    """Create tables and indexes if they don't exist. Safe to call repeatedly.

    Also migrates older databases by adding columns that were introduced
    after the initial schema.
    """
    await db.execute(_CREATE_JOBS)
    await db.execute(_CREATE_IDX)
    # Migration: add columns for databases created before this feature.
    for col, defn in (
        ("input_tokens",   "INTEGER NOT NULL DEFAULT 0"),
        ("output_tokens",  "INTEGER NOT NULL DEFAULT 0"),
        ("model_used",     "TEXT NOT NULL DEFAULT ''"),
        ("remote_cleaned", "INTEGER NOT NULL DEFAULT 0"),
        ("array_spec",     "TEXT NOT NULL DEFAULT ''"),
        ("status_detail",  "TEXT NOT NULL DEFAULT ''"),
        ("efficiency",     "TEXT NOT NULL DEFAULT ''"),
        ("alloc_cpus",      "INTEGER"),
        ("alloc_gpus",      "INTEGER"),
        ("alloc_nodes",     "INTEGER"),
        ("runtime_seconds", "INTEGER"),
        ("core_seconds",    "REAL"),
        ("gpu_seconds",     "REAL"),
        ("exit_code",      "TEXT NOT NULL DEFAULT ''"),
        ("alloc_billing",   "INTEGER"),
        ("billing_seconds", "REAL"),
        ("accounting_source", "TEXT NOT NULL DEFAULT ''"),
        ("measured_at",     "REAL"),
        ("sync_attempts",   "INTEGER NOT NULL DEFAULT 0"),
    ):
        try:
            await db.execute(f"ALTER TABLE jobs ADD COLUMN {col} {defn}")
        except Exception:
            pass  # Column already exists.
    await db.execute(_CREATE_GENERATIONS)
    await _seed_generations(db)
    await db.commit()


async def _seed_generations(db: "aiosqlite.Connection") -> None:
    """Carry an existing database's job usage into the generations table once.

    Spend is counted from generations, not from jobs (#66), so without this an
    upgrade would show a lifetime total of zero for someone with a year of
    history. One row per job that recorded usage, marked seeded so it happens
    exactly once and so the rows stay distinguishable from real generations.

    A job row records only the last generation that produced it, which is the
    undercount this table exists to fix; seeding cannot invent the calls that
    were never recorded, so a seeded history stays a floor. Everything from
    here on is counted properly.
    """
    async with db.execute("SELECT COUNT(*) FROM generations WHERE seeded = 1") as cur:
        row = await cur.fetchone()
    if row and row[0]:
        return
    await db.execute(
        """
        INSERT INTO generations (
            generated_at, cluster_name, model, input_tokens, output_tokens, seeded
        )
        SELECT submitted_at, cluster_name, model_used, input_tokens, output_tokens, 1
        FROM jobs
        WHERE input_tokens > 0 OR output_tokens > 0
        """
    )


# ── Write operations ──────────────────────────────────────────────────────────

async def insert_job(db: "aiosqlite.Connection", job: JobRecord) -> int:
    """Insert a new job record. Returns the assigned row_id."""
    cur = await db.execute(
        """
        INSERT INTO jobs (
            job_id, job_name, cluster_name, host, user, account,
            partition, script_path, working_dir, local_dir, status,
            submitted_at, walltime, input_tokens, output_tokens, model_used,
            array_spec, status_detail
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job.job_id, job.job_name, job.cluster_name, job.host,
            job.user, job.account, job.partition, job.script_path,
            job.working_dir, job.local_dir, job.status,
            job.submitted_at, job.walltime,
            job.input_tokens, job.output_tokens, job.model_used,
            job.array_spec, job.status_detail,
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
    status_detail: str | None = None,
    efficiency: str | None = None,
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
    if status_detail is not None:
        sets.append("status_detail = ?")
        params.append(status_detail)
    if efficiency is not None:
        sets.append("efficiency = ?")
        params.append(efficiency)

    params.extend([job_id, cluster_name])
    await db.execute(
        f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = ? AND cluster_name = ?",
        params,
    )
    await db.commit()


async def update_accounting(
    db: "aiosqlite.Connection",
    job_id: str,
    cluster_name: str,
    acct: "JobAccounting",
) -> None:
    """Store what sacct reported the scheduler reserved for a finished job.

    A separate writer rather than seven more keyword arguments on
    ``update_status``: these fields are written once, together, from one
    source, and only when a job reaches a terminal state.

    An empty accounting record is a no-op, so a site without an accounting
    database never overwrites a good row with nulls.
    """
    if acct.is_empty:
        return
    await db.execute(
        """
        UPDATE jobs SET
            alloc_cpus = ?, alloc_gpus = ?, alloc_nodes = ?,
            runtime_seconds = ?, core_seconds = ?, gpu_seconds = ?,
            exit_code = ?, accounting_source = 'sacct'
        WHERE job_id = ? AND cluster_name = ?
        """,
        (
            acct.cpus, acct.gpus, acct.nodes,
            acct.runtime_seconds, acct.core_seconds, acct.gpu_seconds,
            acct.exit_code, job_id, cluster_name,
        ),
    )
    await db.commit()


async def update_allocation(
    db: "aiosqlite.Connection",
    job_id: str,
    cluster_name: str,
    alloc: "JobAllocation",
    *,
    measured_at: float,
) -> None:
    """Store the per-task allocation squeue reported, once, when it is known.

    An empty allocation is a no-op, so a squeue that answered nothing never
    replaces one that answered something.
    """
    if alloc.is_empty:
        return
    await db.execute(
        """
        UPDATE jobs SET
            alloc_cpus = ?, alloc_gpus = ?, alloc_nodes = ?, alloc_billing = ?,
            measured_at = COALESCE(measured_at, ?)
        WHERE job_id = ? AND cluster_name = ?
        """,
        (alloc.cpus, alloc.gpus, alloc.nodes, alloc.billing,
         measured_at, job_id, cluster_name),
    )
    await db.commit()


async def accumulate_reserved(
    db: "aiosqlite.Connection",
    job_id: str,
    cluster_name: str,
    *,
    running_tasks: int,
    seconds: float,
    cpus: int | None,
    gpus: int | None,
    billing: int | None,
    now: float,
) -> None:
    """Add one poll interval's worth of reserved resource time.

    ClusterPilot cannot ask SLURM accounting what an array cost on a cluster
    whose sacct is unreachable, so it measures instead: every poll it knows how
    many tasks are running, and multiplies that by the per-task allocation and
    the time since the previous poll. Summed over the job's life that is the
    reserved resource time, accurate to within one poll interval per task
    transition rather than assuming every task ran for the whole wall-clock
    span, which is what a single start-to-finish figure would do.

    Nothing is added when no task is running, so queued time is never charged.
    """
    if running_tasks <= 0 or seconds <= 0:
        await db.execute(
            "UPDATE jobs SET measured_at = ? WHERE job_id = ? AND cluster_name = ?",
            (now, job_id, cluster_name),
        )
        await db.commit()
        return

    task_seconds = running_tasks * seconds
    await db.execute(
        """
        UPDATE jobs SET
            core_seconds    = COALESCE(core_seconds, 0)    + ?,
            gpu_seconds     = COALESCE(gpu_seconds, 0)     + ?,
            billing_seconds = COALESCE(billing_seconds, 0) + ?,
            accounting_source = CASE WHEN accounting_source = 'sacct'
                                     THEN 'sacct' ELSE 'measured' END,
            measured_at = ?
        WHERE job_id = ? AND cluster_name = ?
        """,
        (
            (cpus or 0) * task_seconds,
            (gpus or 0) * task_seconds,
            (billing or 0) * task_seconds,
            now, job_id, cluster_name,
        ),
    )
    await db.commit()


async def record_download_attempt(
    db: "aiosqlite.Connection",
    job_id: str,
    cluster_name: str,
    *,
    synced: bool,
) -> None:
    """Count a results download, whether or not it worked.

    The count is what makes a retry possible at all: ``synced = 0`` on its own
    is also true of a job that failed before producing anything and never
    wanted a download, so retrying on that alone would rsync jobs that have
    nothing to fetch. A non-zero attempt count means a download was genuinely
    tried and did not land (issue #48).
    """
    await db.execute(
        "UPDATE jobs SET synced = ?, sync_attempts = sync_attempts + 1 "
        "WHERE job_id = ? AND cluster_name = ?",
        (1 if synced else 0, job_id, cluster_name),
    )
    await db.commit()


async def get_retryable_downloads(
    db: "aiosqlite.Connection",
    *,
    max_attempts: int = 5,
) -> list[JobRecord]:
    """Finished jobs whose results download failed and is worth trying again.

    Bounded on purpose: a job whose remote directory is gone, or whose local
    path no longer exists, will never succeed, and retrying it every poll
    forever would be a permanent error in the log rather than a warning worth
    reading. After ``max_attempts`` it stops and the jobs screen keeps saying
    the results are not synced, where `r` still works.
    """
    from clusterpilot.cluster.slurm import TERMINAL_STATES
    placeholders = ",".join("?" * len(TERMINAL_STATES))
    async with db.execute(
        f"SELECT * FROM jobs WHERE synced = 0 AND sync_attempts BETWEEN 1 AND ? "
        f"AND remote_cleaned = 0 AND status IN ({placeholders}) "
        f"ORDER BY finished_at DESC",
        [max_attempts - 1, *TERMINAL_STATES],
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_record(r) for r in rows]


async def mark_remote_cleaned(
    db: "aiosqlite.Connection",
    job_id: str,
    cluster_name: str,
) -> None:
    """Record that the remote working directory has been deleted."""
    await db.execute(
        "UPDATE jobs SET remote_cleaned = 1 WHERE job_id = ? AND cluster_name = ?",
        (job_id, cluster_name),
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


async def get_jobs_missing_accounting(
    db: "aiosqlite.Connection",
    *,
    limit: int | None = None,
    cluster_name: str | None = None,
) -> list[JobRecord]:
    """Finished jobs SLURM accounting has never answered about, newest first.

    Keyed on ``accounting_source`` rather than on any figure being NULL, so a
    job ClusterPilot measured for itself is still offered to a later backfill.
    That is deliberate: a measured estimate should be upgraded to a real
    accounting record whenever slurmdbd becomes reachable again, and on the
    Alliance clusters that outage is often temporary (issue #47).

    Newest first because a site's accounting retention is finite: the oldest
    jobs are the ones sacct will have forgotten, so the useful work happens at
    the start of the list.
    """
    from clusterpilot.cluster.slurm import TERMINAL_STATES
    placeholders = ",".join("?" * len(TERMINAL_STATES))
    sql = (
        f"SELECT * FROM jobs WHERE accounting_source != 'sacct' "
        f"AND status IN ({placeholders})"
    )
    params: list[object] = list(TERMINAL_STATES)
    if cluster_name:
        sql += " AND cluster_name = ?"
        params.append(cluster_name)
    sql += " ORDER BY submitted_at DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [_row_to_record(r) for r in rows]


async def record_generation(
    db: "aiosqlite.Connection",
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cluster_name: str = "",
) -> None:
    """Record one billed generation, whatever becomes of the script.

    Called when the generation finishes rather than when a job is submitted,
    because a regenerated, abandoned or truncation-refused script is billed
    exactly like one that reaches sbatch (#66).
    """
    await db.execute(
        """
        INSERT INTO generations (
            generated_at, cluster_name, model, input_tokens, output_tokens
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (time.time(), cluster_name, model, input_tokens, output_tokens),
    )
    await db.commit()


async def get_spend_by_model(
    db: "aiosqlite.Connection",
) -> list[tuple[str, int, int]]:
    """Return (model, input_tokens, output_tokens) grouped by model.

    Grouped rather than totalled because the two models in play are priced 2.5x
    apart and the HARDER JOB switch is per generation: one rate applied to the
    whole history reads an Opus month as a Sonnet one (#66).
    """
    async with db.execute(
        """
        SELECT model,
               COALESCE(SUM(input_tokens), 0),
               COALESCE(SUM(output_tokens), 0)
        FROM generations
        GROUP BY model
        """
    ) as cur:
        rows = await cur.fetchall()
    return [(r[0] or "", r[1], r[2]) for r in rows]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_record(row: tuple) -> JobRecord:  # type: ignore[type-arg]
    values = tuple(row)
    (
        row_id, job_id, job_name, cluster_name, host, user, account,
        partition, script_path, working_dir, local_dir, status,
        submitted_at, started_at, finished_at, walltime, log_path, synced,
        input_tokens, output_tokens, model_used, remote_cleaned, array_spec,
    ) = values[:23]
    # Databases written before status_detail existed simply have no such column.
    try:
        status_detail = row["status_detail"]
    except (IndexError, KeyError, TypeError):
        status_detail = values[23] if len(values) > 23 else ""
    # Same for efficiency, added later still.
    try:
        efficiency = row["efficiency"]
    except (IndexError, KeyError, TypeError):
        efficiency = values[24] if len(values) > 24 else ""
    # Accounting columns, added later still again. Absent on a row written
    # before this release, which reads as None rather than zero.
    acct = values[25:37] + (None,) * max(0, 37 - len(values))
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
        remote_cleaned=bool(remote_cleaned),
        array_spec=array_spec or "",
        status_detail=status_detail or "",
        efficiency=efficiency or "",
        alloc_cpus=acct[0],
        alloc_gpus=acct[1],
        alloc_nodes=acct[2],
        runtime_seconds=acct[3],
        core_seconds=acct[4],
        gpu_seconds=acct[5],
        exit_code=acct[6] or "",
        alloc_billing=acct[7],
        billing_seconds=acct[8],
        accounting_source=acct[9] or "",
        measured_at=acct[10],
        sync_attempts=acct[11] or 0,
    )
