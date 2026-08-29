"""Hosted tier sync: POST job state changes to the ClusterPilot cloud API.

This module is a best-effort fire-and-forget layer. Any error is logged and
swallowed — sync failures must never block the daemon or affect local state.

The endpoints are per-user, authenticated by the hosted bearer token:
    POST {api_url}/jobs                        JobUpsert payload
    GET  {api_url}/notify/preferences/daemon   which events the user wants
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from clusterpilot.config import HostedConfig
from clusterpilot.db import JobRecord

log = logging.getLogger(__name__)

_TIMEOUT = 10.0  # seconds


@dataclass(frozen=True)
class NotificationPreferences:
    """Per-event notification switches held in the user's cloud account.

    Mirrors the booleans stored by the dashboard's Notifications page. Only
    events the dashboard actually offers appear here; anything else the daemon
    sends (the periodic ETA, for instance) stays under local config control.
    """

    started: bool = True
    completed: bool = True
    failed: bool = True
    low_time: bool = True


async def fetch_notification_preferences(
    hosted: HostedConfig,
) -> NotificationPreferences | None:
    """Read the user's cloud notification preferences.

    Returns None when there is no hosted token, when the request fails, or when
    the response is not the expected shape. None means "no opinion from the
    cloud", and the caller falls back to local config alone: a dashboard that
    cannot be reached must never silence a notification.
    """
    if not hosted.api_token:
        return None

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{hosted.api_url.rstrip('/')}/notify/preferences/daemon",
                headers={"Authorization": f"Bearer {hosted.api_token}"},
            )
        if resp.status_code >= 400:
            log.warning(
                "Notification preference fetch returned HTTP %d: %s",
                resp.status_code, resp.text[:200],
            )
            return None
        data = resp.json()
    except Exception:
        log.warning("Notification preference fetch failed, using local config",
                    exc_info=True)
        return None

    if not isinstance(data, dict):
        log.warning("Notification preferences had an unexpected shape, using local config")
        return None

    return NotificationPreferences(
        started=bool(data.get("notify_on_start", True)),
        completed=bool(data.get("notify_on_complete", True)),
        failed=bool(data.get("notify_on_fail", True)),
        low_time=bool(data.get("notify_on_walltime_warn", True)),
    )


def _ts(unix: Optional[float]) -> Optional[str]:
    """Convert a Unix timestamp float to an ISO 8601 string, or None."""
    if unix is None:
        return None
    return datetime.fromtimestamp(unix, tz=timezone.utc).isoformat()


def _elapsed_to_walltime(seconds: float) -> str:
    """Format elapsed seconds as HH:MM:SS."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


async def sync_job(
    job: JobRecord,
    status: str,
    hosted: HostedConfig,
    *,
    log_tail: Optional[str] = None,
) -> bool:
    """POST a job state update to the hosted API.

    No-op if ``hosted.api_token`` is empty (self-hosted users).
    Errors are caught and logged; they never propagate to the caller.

    Returns True if the update was accepted by the API (HTTP < 400), False
    otherwise (no token configured, network error, or an error response). The
    daemon uses this to know whether a state has actually landed in the cloud,
    so it can retry on the next poll rather than assume success.
    """
    if not hosted.api_token:
        return False

    walltime_consumed: Optional[str] = None
    if job.elapsed_seconds is not None:
        walltime_consumed = _elapsed_to_walltime(job.elapsed_seconds)

    # Read the script from the local staging directory if it exists.
    script_content: Optional[str] = None
    if job.local_dir and job.job_name:
        script_path = Path(job.local_dir) / f"{job.job_name}.sh"
        if script_path.exists():
            try:
                script_content = script_path.read_text()
            except OSError:
                pass

    payload: dict = {
        "slurm_job_id": job.job_id,
        "job_name": job.job_name or None,
        "cluster_name": job.cluster_name,
        "partition": job.partition or None,
        "status": status,
        "script": script_content,
        "walltime_requested": job.walltime or None,
        "walltime_consumed": walltime_consumed,
        "submitted_at": _ts(job.submitted_at),
        "started_at": _ts(job.started_at),
        "finished_at": _ts(job.finished_at),
    }
    if log_tail:
        payload["log_tail"] = log_tail

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{hosted.api_url.rstrip('/')}/jobs",
                json=payload,
                headers={"Authorization": f"Bearer {hosted.api_token}"},
            )
        if resp.status_code >= 400:
            log.warning(
                "Hosted sync for job %s returned HTTP %d: %s",
                job.job_id, resp.status_code, resp.text[:200],
            )
            return False
        return True
    except Exception:
        log.warning(
            "Hosted sync failed for job %s (status=%s) — continuing",
            job.job_id, status, exc_info=True,
        )
        return False
