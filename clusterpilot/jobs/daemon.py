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
import os
import time
from pathlib import Path

import aiosqlite

from clusterpilot import paths
from clusterpilot.cluster.slurm import (
    RUNNING_STATES,
    TERMINAL_STATES,
    JobAccounting,
    JobStatus,
    find_array_logs,
    find_log,
    job_accounting,
    job_allocation,
    job_efficiency,
    query_status,
    tail_log,
)
from clusterpilot.config import ClusterProfile, Config, NotificationConfig
from clusterpilot.db import (
    DB_PATH,
    JobRecord,
    get_active_jobs,
    get_all_jobs,
    accumulate_reserved,
    init_db,
    update_accounting,
    update_allocation,
    update_status,
)
from clusterpilot.jobs.fieldnotes import log_completed_job
from clusterpilot.jobs.sync import (
    NotificationPreferences,
    fetch_notification_preferences,
    sync_job,
)
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


class DaemonError(Exception):
    """Base class for daemon errors that a caller is expected to report."""


class ServiceExistsError(DaemonError):
    """Raised when installing would overwrite a different systemd unit.

    A ``daemon install`` from a development checkout used to repoint the
    research unit's ExecStart at the development interpreter, in place and
    without a word (issue #24). Refusing is the only safe default; ``--force``
    is the deliberate override, and it keeps a backup.
    """


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
        # key → last status successfully pushed to the hosted API this run.
        # Lets us reconcile jobs whose transition was missed (e.g. the hosted
        # token was configured after the job had already changed state), rather
        # than only syncing on a live edge.
        self._synced: dict[str, str] = {}
        # Per-event switches read from the user's hosted account at
        # reconcile. None means the cloud has no opinion (self-hosted, or
        # the fetch failed) and local config alone decides.
        self._cloud_prefs: NotificationPreferences | None = None

    # ── Run modes ─────────────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Poll loop. Runs until the task is cancelled (Ctrl-C or systemd stop)."""
        log.info("ClusterPilot daemon started (poll_interval=%ds)",
                 self.config.poll_interval)
        try:
            await self.reconcile_once()
        except Exception:
            log.exception("Error during initial hosted reconcile — continuing")
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
            status = await query_status(profile.host, profile.user, job.job_id)
        except SSHError as exc:
            log.warning("SSH error querying job %s: %s", job.job_id, exc)
            return

        if status is None:
            log.debug("Job %s not found in squeue or sacct — skipping", job.job_id)
            return

        new_status = status.state
        summary = status.summary
        if summary != (job.status_detail or ""):
            # Record the per-task breakdown even when the aggregate state has
            # not moved, so the TUI shows an array's progress between waves.
            # Written against the current state on purpose: the transition
            # below is what records the new one, so a failed transition is
            # retried on the next poll instead of being silently lost.
            await update_status(
                db, job.job_id, job.cluster_name, job.status,
                status_detail=summary,
            )
            job.status_detail = summary

        # Measured before the transition is handled, so the final poll of a
        # job still charges the interval it was running for.
        await self._measure_reserved(db, profile, job, status)

        if new_status != job.status:
            await self._handle_transition(db, profile, job, status)
            return

        if new_status == "RUNNING":
            await self._maybe_notify_running(profile, job)

        # No live transition, but the hosted API may not yet reflect this status
        # (transition missed before the token was set, or a prior sync failed).
        # Re-push once per status until it lands; cheap thereafter.
        if (
            self.config.hosted.api_token
            and self._synced.get(_key(job)) != new_status
        ):
            log_tail = await self._tail_for_sync(profile, job, new_status)
            await self._sync(job, new_status, log_tail=log_tail)

    async def _handle_transition(
        self,
        db: aiosqlite.Connection,
        profile: ClusterProfile,
        job: JobRecord,
        status: JobStatus,
    ) -> None:
        now = time.time()
        key = _key(job)
        new_status = status.state
        log.info("Job %s on %s: %s → %s", job.job_id, profile.name,
                 job.status, new_status)

        if new_status == "RUNNING":
            if job.started_at is not None:
                # An array that dropped back to PENDING between waves is running
                # again, not starting again: no second "started" notification.
                await update_status(db, job.job_id, job.cluster_name, new_status)
                await self._sync(job, new_status)
                return
            # Find the log file path while we're here.
            log_path = await self._find_log_path(profile, job)
            await update_status(
                db, job.job_id, job.cluster_name, new_status,
                started_at=now,
                log_path=log_path,
            )
            job.started_at = now
            job.log_path = log_path
            try:
                if self._should_notify("started"):
                    await notify_started(self._notifications(), job)
            except Exception:
                log.warning("Failed to send start notification for %s", job.job_id, exc_info=True)
            await self._sync(job, new_status)

        elif new_status in TERMINAL_STATES:
            # Asked for once, here, because seff only has an answer after the
            # job leaves the queue and the answer never changes afterwards.
            # Fetched before the notifications so they can carry it.
            efficiency = await self._job_efficiency(profile, job)
            acct = await self._job_accounting(profile, job)
            await update_status(
                db, job.job_id, job.cluster_name, new_status,
                finished_at=now,
                efficiency=efficiency or None,
            )
            await update_accounting(db, job.job_id, job.cluster_name, acct)
            job.finished_at = now
            job.efficiency = efficiency
            if not acct.is_empty:
                # sacct is authoritative where it answers, so it replaces
                # whatever was measured. Where it does not, the measured
                # figures stand and keep saying so.
                job.alloc_cpus = acct.cpus
                job.alloc_gpus = acct.gpus
                job.alloc_nodes = acct.nodes
                job.runtime_seconds = acct.runtime_seconds
                job.core_seconds = acct.core_seconds
                job.gpu_seconds = acct.gpu_seconds
                job.exit_code = acct.exit_code
                job.accounting_source = "sacct"
            elif job.finished_at and job.started_at and not job.runtime_seconds:
                job.runtime_seconds = int(job.finished_at - job.started_at)

            if new_status == "COMPLETED":
                await self._sync_and_notify_completed(db, profile, job, new_status)
            elif status.counts.get("COMPLETED", 0) > 0:
                # A mixed array: some tasks produced results worth keeping, so
                # pull them back before reporting the failure.
                await self._sync_and_notify_partial(db, profile, job, new_status)
            else:
                await self._notify_failed(profile, job, new_status)

            # Clean up ETA tracking for this job.
            self._last_eta.pop(key, None)
            self._low_warned.discard(key)

        else:
            # Any other status change (e.g., PENDING re-queued) — just update.
            await update_status(db, job.job_id, job.cluster_name, new_status)

    async def _download_results(
        self,
        profile: ClusterProfile,
        job: JobRecord,
    ) -> bool:
        """Pull the remote working directory into local_dir/results.

        Returns True when the rsync succeeded. Never raises.
        """
        local_results = Path(job.local_dir) / "results"
        try:
            await download(
                profile.host, profile.user,
                job.working_dir, local_results,
                excludes=list(self.config.defaults.download_excludes),
            )
            log.info("Results synced for job %s → %s", job.job_id, local_results)
            return True
        except RsyncError:
            log.exception("rsync failed for job %s — results not synced", job.job_id)
            return False

    async def _sync_and_notify_completed(
        self,
        db: aiosqlite.Connection,
        profile: ClusterProfile,
        job: JobRecord,
        status: str,
    ) -> None:
        synced = await self._download_results(profile, job)

        await update_status(
            db, job.job_id, job.cluster_name, status,
            synced=synced,
        )
        job.synced = synced
        try:
            if self._should_notify("completed"):
                await notify_completed(self._notifications(), job)
        except Exception:
            log.warning("Failed to send completion notification for %s", job.job_id, exc_info=True)

        # Best-effort: log the completed run into local Fieldnotes. Only after a
        # successful download, so incomplete results are never logged. The helper
        # swallows everything; this outer guard is belt-and-braces.
        if synced:
            try:
                await asyncio.to_thread(log_completed_job, job, self.config)
            except Exception:
                log.warning("Fieldnotes logging failed for %s, continuing",
                            job.job_id, exc_info=True)

        # Fetch the log tail for the dashboard.
        log_tail = ""
        if job.log_path:
            try:
                log_tail = await tail_log(profile.host, profile.user, job.log_path)
            except SSHError:
                pass
        await self._sync(job, status, log_tail=log_tail or None)

    async def _sync_and_notify_partial(
        self,
        db: aiosqlite.Connection,
        profile: ClusterProfile,
        job: JobRecord,
        status: str,
    ) -> None:
        """Terminal array where some tasks completed and some did not.

        The results of the tasks that did finish are downloaded first, then the
        job is reported as failed. Nothing is logged to Fieldnotes: a partial
        array is not a scientific record.
        """
        synced = await self._download_results(profile, job)
        await update_status(
            db, job.job_id, job.cluster_name, status,
            synced=synced,
        )
        job.synced = synced
        await self._notify_failed(profile, job, status)

    async def _job_efficiency(
        self,
        profile: ClusterProfile,
        job: JobRecord,
    ) -> str:
        """CPU and memory efficiency for a finished job, "" when unavailable.

        seff reports per array task, not per array, so the lowest task stands
        in for the job the same way its log does.
        """
        target = job.job_id
        if job.array_spec:
            tasks = await self._array_task_logs(profile, job)
            if tasks:
                target = f"{job.job_id}_{next(iter(tasks))}"
        try:
            return await job_efficiency(profile.host, profile.user, target)
        except Exception:
            log.debug("seff failed for job %s, continuing", job.job_id, exc_info=True)
            return ""

    async def _measure_reserved(
        self,
        db: aiosqlite.Connection,
        profile: ClusterProfile,
        job: JobRecord,
        status: JobStatus,
    ) -> None:
        """Integrate reserved resource time over this poll interval.

        Exists because sacct cannot reach slurmdbd from an Alliance login node
        (issue #47), so on the clusters ClusterPilot is mostly used on there is
        no accounting record to read afterwards. squeue talks to slurmctld,
        which does answer, and it answers only while the job is in the queue,
        so the measurement has to happen as the job runs rather than once at
        the end.

        Never raises: a failure here must not cost a status update.
        """
        try:
            running = sum(
                count for state, count in status.counts.items()
                if state in RUNNING_STATES
            )
            now = time.time()

            if job.alloc_cpus is None and job.alloc_billing is None and running:
                alloc = await job_allocation(profile.host, profile.user, job.job_id)
                if alloc.is_empty:
                    return
                await update_allocation(
                    db, job.job_id, job.cluster_name, alloc, measured_at=now,
                )
                job.alloc_cpus = alloc.cpus
                job.alloc_gpus = alloc.gpus
                job.alloc_nodes = alloc.nodes
                job.alloc_billing = alloc.billing
                job.measured_at = job.measured_at or now
                # No time has passed since the allocation became known, so
                # there is nothing to charge for yet.
                return

            if job.measured_at is None:
                return

            elapsed = now - job.measured_at
            await accumulate_reserved(
                db, job.job_id, job.cluster_name,
                running_tasks=running,
                seconds=elapsed,
                cpus=job.alloc_cpus,
                gpus=job.alloc_gpus,
                billing=job.alloc_billing,
                now=now,
            )
            job.measured_at = now
            if running > 0:
                task_seconds = running * elapsed
                job.core_seconds = (job.core_seconds or 0) + (job.alloc_cpus or 0) * task_seconds
                job.gpu_seconds = (job.gpu_seconds or 0) + (job.alloc_gpus or 0) * task_seconds
                job.billing_seconds = (
                    (job.billing_seconds or 0) + (job.alloc_billing or 0) * task_seconds
                )
                if job.accounting_source != "sacct":
                    job.accounting_source = "measured"
        except Exception:
            log.debug("Reserved-time measurement failed for %s, continuing",
                      job.job_id, exc_info=True)

    async def _job_accounting(
        self,
        profile: ClusterProfile,
        job: JobRecord,
    ) -> JobAccounting:
        """What the scheduler reserved for a finished job, empty when unknown.

        Unlike seff, sacct answers for the whole array from the master job id,
        so there is no per-task probing to do here.
        """
        try:
            return await job_accounting(profile.host, profile.user, job.job_id)
        except Exception:
            log.debug("sacct accounting failed for job %s, continuing", job.job_id, exc_info=True)
            return JobAccounting()

    async def _array_task_logs(
        self,
        profile: ClusterProfile,
        job: JobRecord,
    ) -> dict[str, str]:
        """Per-task logs for an array job, ordered by task index. {} otherwise."""
        if not job.array_spec:
            return {}
        try:
            return await find_array_logs(
                profile.host, profile.user,
                job.job_name, job.job_id, job.working_dir,
            )
        except SSHError:
            return {}

    async def _find_log_path(
        self,
        profile: ClusterProfile,
        job: JobRecord,
    ) -> str | None:
        """Locate this job's stdout log, array-aware.

        An array's tasks write ``%x-%A-%a.out``, which none of ``find_log``'s
        patterns match, so an array job's log_path stayed NULL and TAIL, LOG and
        the failure excerpt all had nothing to work with. The lowest task's log
        stands in for the job.
        """
        tasks = await self._array_task_logs(profile, job)
        if tasks:
            return next(iter(tasks.values()))
        try:
            return await find_log(
                profile.host, profile.user,
                job.job_name, job.job_id, job.working_dir,
            )
        except SSHError:
            return None

    async def _failure_excerpt(
        self,
        profile: ClusterProfile,
        job: JobRecord,
    ) -> str:
        """Log tail for a failure notification, array-aware.

        For an array, task 0 is often the one that completed cleanly and wrote
        nothing useful, so the first task with a non-empty tail is used instead.
        Three tasks is enough to find one without turning a notification into a
        long series of SSH round trips.
        """
        for path in list((await self._array_task_logs(profile, job)).values())[:3]:
            try:
                tail = await tail_log(profile.host, profile.user, path)
            except SSHError:
                continue
            if tail.strip():
                return tail

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
                return ""
        if not log_path:
            return ""
        try:
            return await tail_log(profile.host, profile.user, log_path)
        except SSHError:
            return ""

    async def _notify_failed(
        self,
        profile: ClusterProfile,
        job: JobRecord,
        status: str,
    ) -> None:
        log_tail = await self._failure_excerpt(profile, job)
        try:
            if self._should_notify("failed"):
                await notify_failed(self._notifications(), job, log_tail)
        except Exception:
            log.warning("Failed to send failure notification for %s", job.job_id, exc_info=True)
        await self._sync(job, status, log_tail=log_tail or None)

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
                if self._should_notify("low_time"):
                    await notify_low_time(
                        self._notifications(), job, int(remaining_min),
                    )
            except Exception:
                log.warning("Failed low-time notification for %s", job.job_id, exc_info=True)
            return

        # Periodic ETA update every 30 min (skip if low-time already warned).
        last = self._last_eta.get(key, 0.0)
        if now - last >= _ETA_INTERVAL and key not in self._low_warned:
            self._last_eta[key] = now
            try:
                if self._should_notify("eta"):
                    await notify_eta(
                        self._notifications(), job, int(remaining_min),
                    )
            except Exception:
                log.warning("Failed ETA notification for %s", job.job_id, exc_info=True)

    def _should_notify(self, event: str) -> bool:
        """Whether the hosted account allows this event to be notified.

        True when there are no cloud preferences, so a self-hosted install (or
        an unreachable dashboard) is governed by local config alone. Events the
        dashboard does not offer a switch for are always allowed.
        """
        if self._cloud_prefs is None:
            return True
        return bool(getattr(self._cloud_prefs, event, True))

    def _notifications(self) -> NotificationConfig:
        """Where notifications go: the dashboard's topic when set, else config.toml.

        Issue #43. The dashboard stores a topic URL, so a URL there also picks
        the server; a bare topic keeps the local ``ntfy_server``.
        """
        if self._cloud_prefs is None or not self._cloud_prefs.ntfy_topic:
            return self.config.notifications
        return self.config.notifications.with_topic(self._cloud_prefs.ntfy_topic)

    # ── Hosted sync ───────────────────────────────────────────────────────────

    async def _sync(
        self,
        job: JobRecord,
        status: str,
        *,
        log_tail: str | None = None,
    ) -> None:
        """Push a state to the hosted API and remember it only if it landed."""
        ok = await sync_job(job, status, self.config.hosted, log_tail=log_tail)
        if ok:
            self._synced[_key(job)] = status

    async def _tail_for_sync(
        self,
        profile: ClusterProfile,
        job: JobRecord,
        status: str,
    ) -> str | None:
        """Best-effort log tail for a running/terminal job, for the dashboard."""
        if not job.log_path:
            return None
        if status != "RUNNING" and status not in TERMINAL_STATES:
            return None
        try:
            return (await tail_log(profile.host, profile.user, job.log_path)) or None
        except SSHError:
            return None

    async def reconcile_once(self) -> None:
        """Re-push the current stored status of recent jobs to the hosted API.

        Runs once at daemon start. Covers jobs whose state transition was never
        synced — most importantly terminal jobs, which ``poll_once`` skips
        (``get_active_jobs`` excludes them). Only jobs whose last-synced status
        differs from their stored status are pushed, so repeated restarts within
        a session stay cheap.
        """
        if not self.config.hosted.api_token:
            return

        # Which events the user has switched on in the dashboard. Best effort:
        # a failure leaves the previous answer (or None) in place.
        prefs = await fetch_notification_preferences(self.config.hosted)
        if prefs is not None:
            self._cloud_prefs = prefs
            if prefs.ntfy_topic and self._notifications() != self.config.notifications:
                log.info(
                    "Notifications go to the dashboard's ntfy topic %s, "
                    "not the one in config.toml",
                    self._notifications().resolved_url,
                )

        async with aiosqlite.connect(self.db_path) as db:
            await init_db(db)
            jobs = await get_all_jobs(db, limit=200)

        by_cluster: dict[str, list[JobRecord]] = {}
        for job in jobs:
            if self._synced.get(_key(job)) == job.status:
                continue
            by_cluster.setdefault(job.cluster_name, []).append(job)

        for cluster_name, cluster_jobs in by_cluster.items():
            profile = self.config.get_cluster(cluster_name)
            connected = (
                profile is not None and is_connected(profile.host, profile.user)
            )
            for job in cluster_jobs:
                log_tail = None
                if connected:
                    log_tail = await self._tail_for_sync(profile, job, job.status)
                await self._sync(job, job.status, log_tail=log_tail)


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
{environment}ExecStart={python} -m clusterpilot daemon run
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
"""

# Resolved once at import, and profile-qualified when CLUSTERPILOT_HOME is set,
# so a second profile can never install over the first one's unit (see paths.py).
_SERVICE_NAME = paths.service_name()
_SERVICE_PATH = paths.service_path()


def _service_text(python: str) -> str:
    """Render the unit file for *python*, carrying the profile with it.

    When CLUSTERPILOT_HOME is set, the unit exports it too: systemd starts the
    daemon with a bare environment, so without this line the installed daemon
    would poll the default profile's database rather than the one the unit was
    installed from.
    """
    home_override = os.environ.get(paths.HOME_ENV_VAR, "").strip()
    environment = (
        f"Environment={paths.HOME_ENV_VAR}={paths.home()}\n" if home_override else ""
    )
    return _SERVICE_TEMPLATE.format(python=python, environment=environment)


def _exec_start(unit_text: str) -> str:
    """The unit's ExecStart line, "" when it has none."""
    for line in unit_text.splitlines():
        if line.startswith("ExecStart="):
            return line.strip()
    return ""


def write_service_file(
    python_path: str | None = None,
    *,
    force: bool = False,
) -> Path:
    """Write the systemd user service unit. Returns the path written.

    Raises ``ServiceExistsError`` when a unit is already there and its
    ExecStart differs from the one about to be written, because that is the
    case where installing would silently hijack another install's daemon.
    ``force=True`` overwrites it, keeping the old unit as ``<unit>.bak``.
    """
    import shutil
    import sys

    py = python_path or sys.executable
    text = _service_text(py)

    if _SERVICE_PATH.exists():
        existing = _SERVICE_PATH.read_text()
        existing_exec = _exec_start(existing)
        if existing_exec and existing_exec != _exec_start(text):
            if not force:
                raise ServiceExistsError(
                    f"{_SERVICE_PATH} already exists and runs a different "
                    f"command:\n  {existing_exec}\nwhereas this install would "
                    f"write:\n  {_exec_start(text)}\n"
                    f"Overwriting it would repoint an existing daemon at this "
                    f"interpreter. Re-run with --force to replace it (the "
                    f"current unit is kept as {_SERVICE_PATH.name}.bak), or set "
                    f"{paths.HOME_ENV_VAR} to install under a separate profile."
                )
            backup = _SERVICE_PATH.with_name(_SERVICE_PATH.name + ".bak")
            shutil.copy2(_SERVICE_PATH, backup)
            log.info("Existing unit backed up to %s", backup)

    _SERVICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SERVICE_PATH.write_text(text)
    return _SERVICE_PATH
