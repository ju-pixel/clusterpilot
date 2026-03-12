"""rsync-over-SSH helpers for uploading job files and downloading results.

Uses the existing ControlMaster socket so no re-authentication is needed.
Progress lines are streamed to an optional callback for the TUI to display.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from clusterpilot.ssh.connection import SSHError

# Must match the value in connection.py — both derive from Path.home().
_CONTROL_PATH = str(Path.home() / ".ssh" / "cm_%h_%p_%r")

_SSH_TRANSPORT = (
    f"ssh -o ControlPath={_CONTROL_PATH} -o ControlMaster=no -o BatchMode=yes"
)


class RsyncError(SSHError):
    """Raised when rsync exits with a non-zero code."""


def read_ignore_file(project_dir: Path) -> list[str]:
    """Read .clusterpilot_ignore from project_dir and return rsync patterns.

    Lines starting with # are comments. Empty lines are skipped.
    Returns an empty list if the file does not exist.
    Patterns are passed directly to rsync --exclude, so use rsync glob syntax:
    trailing / for directories (data/), wildcards for file types (*.h5).
    """
    ignore_file = project_dir / ".clusterpilot_ignore"
    if not ignore_file.exists():
        return []
    return [
        line.strip()
        for line in ignore_file.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


async def upload(
    host: str,
    user: str,
    local_path: Path,
    remote_path: str,
    *,
    excludes: list[str] | None = None,
    progress_callback: Callable[[str], None] | None = None,
    timeout: float = 3600.0,
) -> None:
    """Upload contents of local_path to remote_path on host.

    Trailing slash semantics: uploads the *contents* of local_path into
    remote_path (rsync convention: src/ → dst/).

    excludes: list of rsync --exclude patterns, e.g. ["data/", "*.tmp"].
    """
    await _run(
        src=str(local_path).rstrip("/") + "/",
        dst=f"{user}@{host}:{remote_path.rstrip('/')}/",
        excludes=excludes or [],
        progress_callback=progress_callback,
        timeout=timeout,
    )


async def upload_file(
    host: str,
    user: str,
    local_file: Path,
    remote_dir: str,
    *,
    progress_callback: Callable[[str], None] | None = None,
    timeout: float = 3600.0,
) -> None:
    """Upload a single file to remote_dir on host.

    The file lands as remote_dir/<filename>. The remote directory must
    already exist (call run_remote mkdir -p first if needed).
    """
    await _run(
        src=str(local_file),
        dst=f"{user}@{host}:{remote_dir.rstrip('/')}/",
        excludes=[],
        progress_callback=progress_callback,
        timeout=timeout,
    )


async def download(
    host: str,
    user: str,
    remote_path: str,
    local_path: Path,
    *,
    progress_callback: Callable[[str], None] | None = None,
    timeout: float = 3600.0,
) -> None:
    """Download contents of remote_path from host to local_path.

    Never passes --delete, so local files absent from the remote are preserved.
    New or updated remote files are merged in.
    """
    local_path.mkdir(parents=True, exist_ok=True)
    await _run(
        src=f"{user}@{host}:{remote_path.rstrip('/')}/",
        dst=str(local_path).rstrip("/") + "/",
        excludes=[],
        progress_callback=progress_callback,
        timeout=timeout,
    )


async def _run(
    src: str,
    dst: str,
    *,
    excludes: list[str],
    progress_callback: Callable[[str], None] | None = None,
    timeout: float,
) -> None:
    exclude_args: list[str] = []
    for pattern in excludes:
        exclude_args += ["--exclude", pattern]

    proc = await asyncio.create_subprocess_exec(
        "rsync",
        "-az",
        "--progress",
        *exclude_args,
        "-e", _SSH_TRANSPORT,
        src,
        dst,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,   # merge so errors show in progress
    )

    lines: list[str] = []

    async def _drain() -> None:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode().strip()
            if line:
                lines.append(line)
                if progress_callback:
                    progress_callback(line)

    try:
        await asyncio.wait_for(_drain(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RsyncError(f"rsync timed out after {timeout}s: {src} → {dst}")

    await proc.wait()
    if proc.returncode != 0:
        tail = "\n".join(lines[-5:])
        raise RsyncError(
            f"rsync failed (exit {proc.returncode}): {src} → {dst}\n{tail}"
        )
