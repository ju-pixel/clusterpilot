"""Background poll daemon.

Watches active SLURM jobs and reacts to state transitions:
  PENDING → RUNNING    notify started, locate log file
  *       → COMPLETED  rsync pull results → local_dir/results/, notify
  *       → FAILED     fetch log tail, notify with excerpt
  *       → TIMEOUT    fetch log tail, notify
  RUNNING (ongoing)    send ETA update every 30 min; warn when < 30 min left

Three run modes (all use PollDaemon):
  embedded   — called from the TUI as an asyncio task
  standalone — `clusterpilot daemon run` (blocks until Ctrl-C)
  systemd    — `clusterpilot daemon install` writes a user service unit
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import aiosqlite

from clusterpilot.cluster.slurm import (
    TERMINAL_STATES,
    find_log,
    job_status,
    tail_log,
)
from clusterpilot.config import ClusterProfile, Config
from clusterpilot.db import DB_PATH, JobRecord, get_active_jobs, init_db, update_status
from clusterpilot.jobs.sync import sync_job
from clusterpilot.notify.ntfy import (
    notify_completed,
    notify_eta,
    notify_failed,
    notify_low_time,
    notify_started,
)
from clusterpilot.ssh.connection import SSHError, is_connected
from clusterpilot.ssh.rsync import RsyncError, download

log = logging.getLogger(__name__)

_ETA_INTERVAL = 1800      # seconds between ETA notifications (30 min)
_LOW_TIME_THRESHOLD = 30  # minutes remaining before low-time warning


class PollDaemon:
    """Poll active jobs and react to state changes.

    Instantiate once, then call run_forever() or poll_once() as needed.
    """

    def __init__(self, config: Config, db_path: Path = DB_PATH) -> None:
        self.config = config
        self.db_path = db_path
        # In-memory notification state — resets on daemon restart (acceptable).
        self._last_eta: dict[str, float] = {}      # key → last ETA notify time
        self._low_warned: set[str] = set()          # keys that got low-time warn

    # ── Run modes ─────────────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Poll loop. Runs until the task is cancelled (Ctrl-C or systemd stop)."""
        log.info("ClusterPilot daemon started (poll_interval=%ds)",
                 self.config.poll_interval)
        while True:
            try:
                await self.poll_once()
            except Exception:
                log.exception("Unexpected error in poll cycle — continuing")
            await asyncio.sleep(self.config.poll_interval)

    async def poll_once(self) -> None:
        """Single poll cycle: check every active job across all clusters."""
        async with aiosqlite.connect(self.db_path) as db:
            await init_db(db)
            jobs = await get_active_jobs(db)

        if not jobs:
            return

        # Group jobs by cluster so we batch per-cluster SSH checks.
        by_cluster: dict[str, list[JobRecord]] = {}
        for job in jobs:
            by_cluster.setdefault(job.cluster_name, []).append(job)

        for cluster_name, cluster_jobs in by_cluster.items():
            profile = self.config.get_cluster(cluster_name)
            if profile is None:
                log.warning("Cluster %r in DB but not in config — skipping", cluster_name)
                continue
            async with aiosqlite.connect(self.db_path) as db:
                await init_db(db)
                await self._poll_cluster(db, profile, cluster_jobs)

    # ── Per-cluster polling ───────────────────────────────────────────────────

    async def _poll_cluster(
        self,
        db: aiosqlite.Connection,
        profile: ClusterProfile,
        jobs: list[JobRecord],
    ) -> None:
        if not is_connected(profile.host, profile.user):
            log.warning(
                "No active SSH socket for %s@%s — skipping poll. "
                "Re-open the app to reconnect.",
                profile.user, profile.host,
            )
            return

        results = await asyncio.gather(
            *[self._poll_job(db, profile, job) for job in jobs],
            return_exceptions=True,
        )
        for job, result in zip(jobs, results):
            if isinstance(result, Exception):
                log.error("Error polling job %s on %s: %s",
                          job.job_id, profile.name, result)

    # ── Per-job logic ─────────────────────────────────────────────────────────

    async def _poll_job(
        self,
        db: aiosqlite.Connection,
        profile: ClusterProfile,
        job: JobRecord,
    ) -> None:
        try:
            new_status = await job_status(profile.host, profile.user, job.job_id)
        except SSHError as exc:
            log.warning("SSH error querying job %s: %s", job.job_id, exc)
            return

        if new_status is None:
            log.debug("Job %s not found in squeue or sacct — skipping", job.job_id)
            return

        if new_status != job.status:
            await self._handle_transition(db, profile, job, new_status)
        elif new_status == "RUNNING":
            await self._maybe_notify_running(profile, job)

    async def _handle_transition(
        self,
        db: aiosqlite.Connection,
        profile: ClusterProfile,
        job: JobRecord,
        new_status: str,
    ) -> None:
        now = time.time()
        key = _key(job)
        log.info("Job %s on %s: %s → %s", job.job_id, profile.name,
                 job.status, new_status)

        if new_status == "RUNNING":
            # Find the log file path while we're here.
            log_path = await find_log(
                profile.host, profile.user,
                job.job_name, job.job_id, job.working_dir,
            )
            await update_status(
                db, job.job_id, job.cluster_name, new_status,
                started_at=now,
                log_path=log_path,
            )
            job.started_at = now
            job.log_path = log_path
            try:
                await notify_started(self.config.notifications, job)
            except Exception:
                log.warning("Failed to send start notification for %s", job.job_id, exc_info=True)
            await sync_job(job, new_status, self.config.hosted)

        elif new_status in TERMINAL_STATES:
            await update_status(
                db, job.job_id, job.cluster_name, new_status,
                finished_at=now,
            )
            job.finished_at = now

            if new_status == "COMPLETED":
                await self._sync_and_notify_completed(db, profile, job, new_status)
            else:
                await self._notify_failed(profile, job, new_status)

            # Clean up ETA tracking for this job.
            self._last_eta.pop(key, None)
            self._low_warned.discard(key)

        else:
            # Any other status change (e.g., PENDING re-queued) — just update.
            await update_status(db, job.job_id, job.cluster_name, new_status)

    async def _sync_and_notify_completed(
        self,
        db: aiosqlite.Connection,
        profile: ClusterProfile,
        job: JobRecord,
        status: str,
    ) -> None:
        local_results = Path(job.local_dir) / "results"
        synced = False
        try:
            await download(
                profile.host, profile.user,
                job.working_dir, local_results,
                excludes=list(self.config.defaults.download_excludes),
            )
            synced = True
            log.info("Results synced for job %s → %s", job.job_id, local_results)
        except RsyncError:
            log.exception("rsync failed for job %s — results not synced", job.job_id)

        await update_status(
            db, job.job_id, job.cluster_name, status,
            synced=synced,
        )
        job.synced = synced
        try:
            await notify_completed(self.config.notifications, job)
        except Exception:
            log.warning("Failed to send completion notification for %s", job.job_id, exc_info=True)

        # Fetch the log tail for the dashboard.
        log_tail = ""
        if job.log_path:
            try:
                log_tail = await tail_log(profile.host, profile.user, job.log_path)
            except SSHError:
                pass
        await sync_job(job, status, self.config.hosted, log_tail=log_tail or None)

    async def _notify_failed(
        self,
        profile: ClusterProfile,
        job: JobRecord,
        status: str,
    ) -> None:
        log_tail = ""
        log_path = job.log_path
        if not log_path:
            # Job may have run briefly without the daemon catching the RUNNING
            # transition (e.g., cancelled faster than the poll interval).
            try:
                log_path = await find_log(
                    profile.host, profile.user,
                    job.job_name, job.job_id, job.working_dir,
                )
            except SSHError:
                pass
        if log_path:
            try:
                log_tail = await tail_log(profile.host, profile.user, log_path)
            except SSHError:
                pass
        try:
            await notify_failed(self.config.notifications, job, log_tail)
        except Exception:
            log.warning("Failed to send failure notification for %s", job.job_id, exc_info=True)
        await sync_job(job, status, self.config.hosted, log_tail=log_tail or None)

    # ── ETA / low-time notifications ──────────────────────────────────────────

    async def _maybe_notify_running(
        self,
        profile: ClusterProfile,
        job: JobRecord,
    ) -> None:
        if job.started_at is None or not job.walltime:
            return

        key = _key(job)
        now = time.time()
        walltime_s = _parse_walltime_seconds(job.walltime)
        elapsed = now - job.started_at
        remaining_s = max(0.0, walltime_s - elapsed)
        remaining_min = remaining_s / 60

        # Low-time warning: once per job when < 30 min remain.
        if remaining_min < _LOW_TIME_THRESHOLD and key not in self._low_warned:
            self._low_warned.add(key)
            try:
                await notify_low_time(
                    self.config.notifications, job, int(remaining_min),
                )
            except Exception:
                log.warning("Failed low-time notification for %s", job.job_id, exc_info=True)
            return

        # Periodic ETA update every 30 min (skip if low-time already warned).
        last = self._last_eta.get(key, 0.0)
        if now - last >= _ETA_INTERVAL and key not in self._low_warned:
            self._last_eta[key] = now
            try:
                await notify_eta(
                    self.config.notifications, job, int(remaining_min),
                )
            except Exception:
                log.warning("Failed ETA notification for %s", job.job_id, exc_info=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _key(job: JobRecord) -> str:
    return f"{job.cluster_name}:{job.job_id}"


def _parse_walltime_seconds(walltime: str) -> float:
    """Parse SLURM walltime strings to seconds.

    Accepts: "HH:MM:SS", "D-HH:MM:SS"
    """
    days = 0
    if "-" in walltime:
        day_str, walltime = walltime.split("-", 1)
        days = int(day_str)
    parts = walltime.split(":")
    h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
    return days * 86400 + h * 3600 + m * 60 + s


# ── systemd service helpers ───────────────────────────────────────────────────

_SERVICE_TEMPLATE = """\
[Unit]
Description=ClusterPilot job poll daemon
After=network.target

[Service]
Type=simple
ExecStart={python} -m clusterpilot daemon run
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
"""

_SERVICE_PATH = Path.home() / ".config" / "systemd" / "user" / "clusterpilot-poll.service"


def write_service_file(python_path: str | None = None) -> Path:
    """Write the systemd user service unit. Returns the path written."""
    import sys
    py = python_path or sys.executable
    _SERVICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SERVICE_PATH.write_text(_SERVICE_TEMPLATE.format(python=py))
    return _SERVICE_PATH
