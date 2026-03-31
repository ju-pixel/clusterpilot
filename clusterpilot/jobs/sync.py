"""Hosted tier sync: POST job state changes to the ClusterPilot cloud API.

This module is a best-effort fire-and-forget layer. Any error is logged and
swallowed — sync failures must never block the daemon or affect local state.

The endpoint is unauthenticated per-user (authenticated via bearer token):
    POST {api_url}/jobs   →  JobUpsert payload
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from clusterpilot.config import HostedConfig
from clusterpilot.db import JobRecord

log = logging.getLogger(__name__)

_TIMEOUT = 10.0  # seconds


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
) -> None:
    """POST a job state update to the hosted API.

    No-op if ``hosted.api_token`` is empty (self-hosted users).
    Errors are caught and logged; they never propagate to the caller.
    """
    if not hosted.api_token:
        return

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
    except Exception:
        log.warning(
            "Hosted sync failed for job %s (status=%s) — continuing",
            job.job_id, status, exc_info=True,
        )
