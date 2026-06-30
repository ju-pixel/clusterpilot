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


# Canonical name first, legacy name second. Both are read and merged so an
# existing .clusterpilot_ignore keeps working after the rename.
_IGNORE_FILENAMES = (".clusterpilotignore", ".clusterpilot_ignore")


def read_ignore_file(project_dir: Path) -> list[str]:
    """Read the per-project ignore file(s) and return rsync exclude patterns.

    Reads ``.clusterpilotignore`` (canonical) and the legacy
    ``.clusterpilot_ignore``; if both exist their patterns are merged, the
    canonical file first, with duplicates removed but order preserved.

    Lines starting with # are comments. Empty lines are skipped. Patterns use
    gitignore-style / rsync glob syntax: a trailing / for directories (``data/``),
    wildcards for file types (``*.h5``). They are passed straight to rsync
    ``--exclude``.

    Returns an empty list if neither file exists.
    """
    patterns: list[str] = []
    seen: set[str] = set()
    for name in _IGNORE_FILENAMES:
        ignore_file = project_dir / name
        if not ignore_file.exists():
            continue
        for line in ignore_file.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped not in seen:
                seen.add(stripped)
                patterns.append(stripped)
    return patterns


async def upload(
    host: str,
    user: str,
    local_path: Path,
    remote_path: str,
    *,
    excludes: list[str] | None = None,
    includes: list[str] | None = None,
    progress_callback: Callable[[str], None] | None = None,
    timeout: float = 3600.0,
) -> None:
    """Upload contents of local_path to remote_path on host.

    Trailing slash semantics: uploads the *contents* of local_path into
    remote_path (rsync convention: src/ → dst/).

    Empty directories are pruned (``--prune-empty-dirs``), so a directory whose
    only contents were excluded is not recreated on the remote.

    excludes: rsync --exclude patterns, e.g. ["data/", "*.tmp"].
    includes: when given, switches to allowlist mode. Only paths matching one
        of these patterns (plus the directories needed to reach them) are
        uploaded; everything else is excluded. excludes still apply on top and
        win, so a user ignore can carve a path out of the allowlist. Patterns
        use rsync syntax, e.g. ["Project.toml", "src/***", "scripts/run.jl"].
    """
    await _run(
        src=str(local_path).rstrip("/") + "/",
        dst=f"{user}@{host}:{remote_path.rstrip('/')}/",
        excludes=excludes or [],
        includes=includes or [],
        prune_empty=True,
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
    excludes: list[str] | None = None,
    progress_callback: Callable[[str], None] | None = None,
    timeout: float = 3600.0,
) -> None:
    """Download contents of remote_path from host to local_path.

    Never passes --delete, so local files absent from the remote are preserved.
    New or updated remote files are merged in.

    excludes: rsync --exclude patterns to skip (e.g. source dirs already local).
    """
    local_path.mkdir(parents=True, exist_ok=True)
    await _run(
        src=f"{user}@{host}:{remote_path.rstrip('/')}/",
        dst=str(local_path).rstrip("/") + "/",
        excludes=excludes or [],
        progress_callback=progress_callback,
        timeout=timeout,
    )


def _build_filter_args(excludes: list[str], includes: list[str]) -> list[str]:
    """Build rsync --exclude/--include filter args.

    rsync applies filter rules in order, first match wins. Excludes are emitted
    first so a user ignore can carve a path out of the allowlist. In allowlist
    mode (``includes`` non-empty) we then permit descending into every directory
    (``--include='*/'``), allow the requested paths, and exclude everything else
    (``--exclude='*'``); combined with --prune-empty-dirs at the call site, only
    the matched files and the directories on the way to them survive.
    """
    args: list[str] = []
    for pattern in excludes:
        args += ["--exclude", pattern]
    if includes:
        args += ["--include", "*/"]
        for pattern in includes:
            args += ["--include", pattern]
        args += ["--exclude", "*"]
    return args


async def _run(
    src: str,
    dst: str,
    *,
    excludes: list[str],
    includes: list[str] | None = None,
    prune_empty: bool = False,
    progress_callback: Callable[[str], None] | None = None,
    timeout: float,
) -> None:
    filter_args = _build_filter_args(excludes, includes or [])

    prune_args = ["--prune-empty-dirs"] if prune_empty else []

    proc = await asyncio.create_subprocess_exec(
        "rsync",
        "-az",
        "--progress",
        *prune_args,
        *filter_args,
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
