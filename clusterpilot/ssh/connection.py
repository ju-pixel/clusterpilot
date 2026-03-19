"""SSH connection management using ControlMaster multiplexing.

Only the first connection to a host requires authentication. Subsequent
connections reuse the existing socket with sub-second latency and survive
laptop sleep, VPN changes, and network drops (until ControlPersist expires).

Usage
-----
    from clusterpilot.ssh.connection import is_connected, open_connection, run_remote

    if not is_connected(host, user):
        open_connection(host, user)   # user authenticates once here

    output = await run_remote(host, user, "squeue -u juliaf -h -o '%i %T'")
"""
from __future__ import annotations

import asyncio
import shlex
import subprocess
from pathlib import Path

# %h, %p, %r are SSH escape sequences expanded by the ssh binary at runtime.
_CONTROL_PATH = str(Path.home() / ".ssh" / "cm_%h_%p_%r")


class SSHError(Exception):
    """Raised when an SSH command fails or times out."""


def is_connected(host: str, user: str) -> bool:
    """Return True if a live ControlMaster socket exists for this host."""
    result = subprocess.run(
        [
            "ssh",
            "-o", f"ControlPath={_CONTROL_PATH}",
            "-O", "check",
            f"{user}@{host}",
        ],
        capture_output=True,
    )
    return result.returncode == 0


def open_connection(host: str, user: str) -> None:
    """Open a ControlMaster connection to host.

    Blocks until authentication is complete, then forks the master to the
    background (ControlPersist=4h). The calling code must have a live TTY
    so the user can type their password or 2FA token.

    Raises subprocess.CalledProcessError if SSH exits non-zero.
    """
    subprocess.run(
        [
            "ssh",
            "-o", "ControlMaster=auto",
            "-o", f"ControlPath={_CONTROL_PATH}",
            "-o", "ControlPersist=4h",
            "-o", "ServerAliveInterval=60",
            "-N",           # no remote command: just establish the master
            f"{user}@{host}",
        ],
        check=True,
    )


def close_connection(host: str, user: str) -> None:
    """Gracefully close the ControlMaster socket for this host."""
    subprocess.run(
        [
            "ssh",
            "-o", f"ControlPath={_CONTROL_PATH}",
            "-O", "exit",
            f"{user}@{host}",
        ],
        capture_output=True,   # suppress "Exit request sent."
    )


async def run_remote(
    host: str,
    user: str,
    cmd: str,
    timeout: float = 30.0,
) -> str:
    """Run *cmd* on the remote host via the existing ControlMaster socket.

    Returns decoded stdout (stripped). Raises :class:`SSHError` on failure
    or timeout. Uses ``BatchMode=yes`` so it fails immediately if no socket
    is active rather than hanging on an auth prompt.

    Args:
        host:    SSH hostname, e.g. ``"yak.hpc.umanitoba.ca"``.
        user:    Remote username.
        cmd:     Shell command to run on the remote host.
        timeout: Seconds before the command is killed and SSHError is raised.
    """
    proc = await asyncio.create_subprocess_exec(
        "ssh",
        "-o", f"ControlPath={_CONTROL_PATH}",
        "-o", "ControlMaster=no",   # never become a new master
        "-o", "BatchMode=yes",      # fail fast if no socket / auth needed
        f"{user}@{host}",
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()   # reap
        raise SSHError(f"Command timed out after {timeout}s: {cmd!r}")

    if proc.returncode != 0:
        err = stderr.decode().strip()
        raise SSHError(
            f"Remote command failed (exit {proc.returncode}): {cmd!r}"
            + (f"\n{err}" if err else "")
        )

    return stdout.decode().strip()


async def remove_remote_dir(host: str, user: str, path: str) -> None:
    """Delete a remote directory via ``rm -rf`` over the ControlMaster socket.

    Only operates on paths that contain ``clusterpilot_jobs`` as a safety
    guard against deleting unintended directories.

    Raises :class:`SSHError` if the path is unsafe or the command fails.
    """
    if not path or "clusterpilot_jobs" not in path:
        raise SSHError(
            f"Refusing to delete {path!r}: path must contain 'clusterpilot_jobs'. "
            "Only ClusterPilot job directories can be cleaned from the TUI."
        )
    await run_remote(host, user, f"rm -rf {shlex.quote(path)}", timeout=60.0)
