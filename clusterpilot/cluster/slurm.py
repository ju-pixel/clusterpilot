"""SLURM commands: submit, poll status, cancel, fetch log output.

All functions require an active SSH ControlMaster socket.
"""
from __future__ import annotations

import re

from clusterpilot.ssh.connection import SSHError, run_remote

_SUBMITTED_RE = re.compile(r"Submitted batch job (\d+)")

# States that mean the job will never run again.
TERMINAL_STATES = frozenset({
    "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT",
    "OUT_OF_MEMORY", "NODE_FAIL",
})


class SlurmError(SSHError):
    """Raised when a SLURM command fails unexpectedly."""


# ── Job submission ────────────────────────────────────────────────────────────

async def submit(
    host: str,
    user: str,
    remote_script_path: str,
    *,
    working_dir: str | None = None,
) -> str:
    """Run sbatch on remote_script_path. Returns the numeric job ID string.

    Args:
        host:               SSH hostname.
        user:               Remote username.
        remote_script_path: Absolute path to the .sh script on the cluster.
        working_dir:        If given, cd here before running sbatch.

    Raises:
        SlurmError: if sbatch output doesn't contain "Submitted batch job NNN".
    """
    cmd = f"sbatch {remote_script_path}"
    if working_dir:
        cmd = f"cd {working_dir} && {cmd}"
    try:
        output = await run_remote(host, user, cmd)
    except SSHError as exc:
        raise SlurmError(f"sbatch failed: {exc}") from exc

    match = _SUBMITTED_RE.search(output)
    if not match:
        raise SlurmError(f"Unexpected sbatch output: {output!r}")
    return match.group(1)


# ── Status polling ────────────────────────────────────────────────────────────

async def job_status(host: str, user: str, job_id: str) -> str | None:
    """Return the SLURM state for job_id, or None if the job cannot be found.

    Strategy:
    1. squeue (fast, in-memory) — works while the job is queued or running.
    2. sacct (historical records) — works after the job has left the queue.

    Common return values: PENDING, RUNNING, COMPLETED, FAILED,
    CANCELLED, TIMEOUT, OUT_OF_MEMORY.
    """
    # 1. squeue — job still in queue
    try:
        out = await run_remote(
            host, user,
            f"squeue -j {job_id} -h -o '%T' 2>/dev/null",
        )
        state = out.strip()
        if state:
            return state
    except SSHError:
        pass

    # 2. sacct — job already finished; -X = summary record only (no steps)
    try:
        out = await run_remote(
            host, user,
            f"sacct -j {job_id} -n -X -o State --parsable2 2>/dev/null",
        )
        for line in out.strip().splitlines():
            # sacct can append "+" for job-step aggregates; strip it.
            # "CANCELLED by 12345" → "CANCELLED"
            state = line.strip().split("+")[0].split()[0]
            if state:
                return state
    except SSHError:
        pass

    return None


# ── Job control ───────────────────────────────────────────────────────────────

async def cancel(host: str, user: str, job_id: str) -> None:
    """Cancel a queued or running SLURM job via scancel."""
    try:
        await run_remote(host, user, f"scancel {job_id}")
    except SSHError as exc:
        raise SlurmError(f"scancel failed for job {job_id}: {exc}") from exc


# ── Log access ────────────────────────────────────────────────────────────────

async def tail_log(
    host: str,
    user: str,
    remote_log_path: str,
    n_lines: int = 50,
) -> str:
    """Return the last n_lines of a remote file. Empty string if not found."""
    try:
        return await run_remote(
            host, user,
            f"tail -n {n_lines} {remote_log_path} 2>/dev/null",
        )
    except SSHError:
        return ""


async def cat_log(
    host: str,
    user: str,
    remote_log_path: str,
) -> str:
    """Return the full contents of a remote log file. Empty string if not found."""
    try:
        return await run_remote(
            host, user,
            f"cat {remote_log_path} 2>/dev/null",
        )
    except SSHError:
        return ""


async def find_log(
    host: str,
    user: str,
    job_name: str,
    job_id: str,
    working_dir: str,
) -> str | None:
    """Locate the SLURM stdout log for this job on the remote host.

    Tries common naming patterns in order:
      <working_dir>/<job_name>-<job_id>.out   (ClusterPilot default: %x-%j.out)
      <working_dir>/slurm-<job_id>.out        (SLURM default)
      <working_dir>/<job_id>.out

    Returns the first path that exists, or None.
    """
    candidates = [
        f"{working_dir}/{job_name}-{job_id}.out",
        f"{working_dir}/slurm-{job_id}.out",
        f"{working_dir}/{job_id}.out",
    ]
    for path in candidates:
        try:
            out = await run_remote(
                host, user,
                f"test -f {path} && echo exists",
            )
            if out.strip() == "exists":
                return path
        except SSHError:
            continue
    return None
