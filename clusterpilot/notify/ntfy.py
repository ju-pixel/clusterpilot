"""ntfy.sh push notifications for job events.

API: POST {server}/{topic} with Title/Priority/Tags headers and a text body.
Errors are raised as NtfyError — callers (daemon) should catch and log.
"""
from __future__ import annotations

import httpx

from clusterpilot.config import NotificationConfig
from clusterpilot.db import JobRecord


class NtfyError(Exception):
    """Raised when the ntfy.sh POST fails."""


# ── Core send ─────────────────────────────────────────────────────────────────

async def send(
    topic: str,
    message: str,
    *,
    title: str = "ClusterPilot",
    priority: str = "default",      # min | low | default | high | urgent
    tags: list[str] | None = None,  # ntfy emoji shortcodes, e.g. ["rocket"]
    server: str = "https://ntfy.sh",
) -> None:
    """POST a notification to ntfy.sh (or a self-hosted instance)."""
    if not topic:
        return   # silently skip if topic not configured

    url = f"{server.rstrip('/')}/{topic}"
    headers: dict[str, str] = {
        "Title": title,
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = ",".join(tags)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                content=message.encode(),
                headers=headers,
                timeout=10.0,
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise NtfyError(f"ntfy POST failed: {exc}") from exc


# ── Job event helpers ─────────────────────────────────────────────────────────

async def notify_started(cfg: NotificationConfig, job: JobRecord) -> None:
    await send(
        cfg.ntfy_topic,
        f"{job.job_name} is now running on {job.cluster_name}\n"
        f"Job ID: {job.job_id}  Partition: {job.partition}",
        title=f"Job started — {job.job_name}",
        priority="default",
        tags=["rocket"],
        server=cfg.ntfy_server,
    )


async def notify_completed(cfg: NotificationConfig, job: JobRecord) -> None:
    await send(
        cfg.ntfy_topic,
        f"{job.job_name} completed on {job.cluster_name}\n"
        f"Results are being synced to your local directory.",
        title=f"Job done ✓ — {job.job_name}",
        priority="high",
        tags=["white_check_mark"],
        server=cfg.ntfy_server,
    )


async def notify_failed(
    cfg: NotificationConfig,
    job: JobRecord,
    log_tail: str = "",
) -> None:
    body = f"{job.job_name} failed on {job.cluster_name} (job {job.job_id})"
    if log_tail:
        # Keep the notification body short; include only the last few lines.
        excerpt = "\n".join(log_tail.splitlines()[-6:])
        body = f"{body}\n\n{excerpt}"
    await send(
        cfg.ntfy_topic,
        body,
        title=f"Job FAILED — {job.job_name}",
        priority="high",
        tags=["x"],
        server=cfg.ntfy_server,
    )


async def notify_eta(
    cfg: NotificationConfig,
    job: JobRecord,
    eta_minutes: int,
) -> None:
    hours, mins = divmod(eta_minutes, 60)
    eta_str = f"{hours}h {mins}m" if hours else f"{mins}m"
    await send(
        cfg.ntfy_topic,
        f"{job.job_name} — estimated {eta_str} remaining\n"
        f"Job ID: {job.job_id}",
        title=f"ETA update — {job.job_name}",
        priority="low",
        tags=["clock1"],
        server=cfg.ntfy_server,
    )


async def notify_low_time(
    cfg: NotificationConfig,
    job: JobRecord,
    minutes_left: int,
) -> None:
    await send(
        cfg.ntfy_topic,
        f"{job.job_name} has only ~{minutes_left} minutes of walltime left!\n"
        f"Job ID: {job.job_id}",
        title=f"Low walltime — {job.job_name}",
        priority="high",
        tags=["warning"],
        server=cfg.ntfy_server,
    )
