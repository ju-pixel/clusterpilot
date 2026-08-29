"""Fill in accounting for jobs that finished before ClusterPilot recorded it.

The daemon writes what sacct reserved at the moment a job reaches a terminal
state. Jobs that finished under an older release therefore have no core-hours,
and a usage report can only count what it was told. sacct keeps its records for
a while after a job leaves the queue, so most of that history can still be
recovered, once, by asking again.

This is deliberately a one-shot command rather than something the daemon does
on a schedule: the window closes when the site's accounting retention expires,
and after that there is nothing to gain from asking repeatedly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import aiosqlite

from clusterpilot.cluster.slurm import JobAccounting, job_accounting_many
from clusterpilot.config import Config
from clusterpilot.db import (
    JobRecord,
    get_jobs_missing_accounting,
    init_db,
    update_accounting,
)
from clusterpilot.jobs.sync import sync_job
from clusterpilot.ssh.connection import SSHError, is_connected, open_connection

log = logging.getLogger(__name__)


@dataclass
class BackfillReport:
    """What one backfill run managed to recover."""

    considered: int = 0
    filled: int = 0
    unknown_to_sacct: int = 0     # sacct answered, and had no record of these
    unreachable: int = 0          # sacct could not be asked at all
    synced: int = 0
    skipped: dict[str, str] = field(default_factory=dict)   # cluster -> why
    errors: dict[str, str] = field(default_factory=dict)    # cluster -> sacct said

    @property
    def nothing_to_do(self) -> bool:
        return self.considered == 0


async def backfill_accounting(
    config: Config,
    db_path,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    cluster_name: str | None = None,
    connect: bool = True,
) -> BackfillReport:
    """Ask sacct about finished jobs that have no accounting, and store it.

    One sacct call covers up to fifty jobs, so a cluster costs one or two
    round-trips rather than one per job. A cluster that cannot be reached is
    recorded in the report and skipped; it never aborts the others.

    With ``dry_run`` no job data is written and nothing is synced, but sacct
    is still asked, so the report says exactly what a real run would recover.
    The database is still opened and ``init_db`` still runs, so a dry run on a
    database from an older release does add the accounting columns. That is
    the same migration opening the TUI performs, not a change to any job.
    """
    report = BackfillReport()

    async with aiosqlite.connect(db_path) as db:
        await init_db(db)
        jobs = await get_jobs_missing_accounting(
            db, limit=limit, cluster_name=cluster_name,
        )
    report.considered = len(jobs)
    if not jobs:
        return report

    by_cluster: dict[str, list[JobRecord]] = {}
    for job in jobs:
        by_cluster.setdefault(job.cluster_name, []).append(job)

    for name, cluster_jobs in by_cluster.items():
        profile = config.get_cluster(name)
        if profile is None:
            report.skipped[name] = "not in config.toml"
            continue

        if not is_connected(profile.host, profile.user):
            if not connect:
                report.skipped[name] = "no SSH connection"
                continue
            try:
                open_connection(profile.host, profile.user)
            except SSHError as exc:
                report.skipped[name] = str(exc)
                continue

        found, error = await job_accounting_many(
            profile.host, profile.user, [j.job_id for j in cluster_jobs],
        )
        if error:
            report.errors[name] = error
        await _store(
            db_path, cluster_jobs, found, config, report,
            dry_run=dry_run, sacct_failed=bool(error),
        )

    return report


async def _store(
    db_path,
    jobs: list[JobRecord],
    found: dict[str, JobAccounting],
    config: Config,
    report: BackfillReport,
    *,
    dry_run: bool,
    sacct_failed: bool = False,
) -> None:
    """Write what sacct returned and push it to the cloud, counting as we go.

    ``sacct_failed`` separates the two reasons a job can come back empty. A
    cluster whose sacct could not be reached has told us nothing about any of
    its jobs, and saying they are past the retention window would be a
    fabrication (issue #46).
    """
    async with aiosqlite.connect(db_path) as db:
        await init_db(db)
        for job in jobs:
            acct = found.get(job.job_id)
            if acct is None or acct.is_empty:
                if sacct_failed:
                    report.unreachable += 1
                else:
                    report.unknown_to_sacct += 1
                continue

            report.filled += 1
            if dry_run:
                continue

            await update_accounting(db, job.job_id, job.cluster_name, acct)
            job.alloc_cpus = acct.cpus
            job.alloc_gpus = acct.gpus
            job.alloc_nodes = acct.nodes
            job.runtime_seconds = acct.runtime_seconds
            job.core_seconds = acct.core_seconds
            job.gpu_seconds = acct.gpu_seconds
            job.exit_code = acct.exit_code

            # Best-effort, exactly as at completion time: a hosted user gets
            # the recovered figures on the dashboard, a self-hosted one has
            # no token and sync_job returns False without doing anything.
            try:
                if await sync_job(job, job.status, config.hosted):
                    report.synced += 1
            except Exception:
                log.debug("Backfill sync failed for job %s", job.job_id, exc_info=True)
