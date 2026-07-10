"""Best-effort logging of completed jobs into the local Fieldnotes CLI.

When a job's results are synced back to the workstation, ClusterPilot can shell
out to the local ``fieldnotes`` binary to record the run in Fieldnotes'
permanent scientific store. This is a local subprocess call to
``fieldnotes log --manifest ...``, NOT an HTTP call to the Fieldnotes API.

The layer is strictly additive and strictly best-effort, mirroring
:mod:`clusterpilot.jobs.sync`: it is off by default, a silent no-op when the
integration is disabled, the binary is absent, or no Fieldnotes run manifest
(``params.json``) is present, and it never raises, slows, or fails a job sync.

Terminology: the "Fieldnotes run manifest" is a tiny ``params.json`` (optionally
a ``run.json``) written beside a run's outputs. It is unrelated to ClusterPilot's
dependency manifest (Project.toml / requirements.txt).

Robustness ladder (see CLAUDE.md "Integration with Fieldnotes"): this module is
rung 1 only. Generated scripts write ``params.json`` and this helper ingests
whatever manifests are present. Hand-written scripts that emit no manifest are
silently skipped. Rungs 2 (CP-tracked fallback params) and 3 (direct-to-cloud
POST) are deliberately not built here.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path

from clusterpilot.config import Config
from clusterpilot.db import JobRecord

log = logging.getLogger(__name__)

_TIMEOUT = 30.0  # seconds; ingestion is a quick local SQLite write
_MANIFEST_NAME = "params.json"
_SENTINEL_NAME = ".fieldnotes-logged"


def log_completed_job(job: JobRecord, config: Config) -> bool:
    """Best-effort: log a completed job's results into local Fieldnotes.

    No-op (returns False) if the integration is disabled, the fieldnotes binary
    is absent, no params.json manifest is present under the results dir, or the
    job has already been logged (sentinel present). Never raises; sync must
    never be affected by Fieldnotes.

    Returns True only when ``fieldnotes log`` ran and exited 0.
    """
    try:
        if not config.fieldnotes.enabled:
            return False

        binary = shutil.which("fieldnotes")
        if binary is None:
            return False

        results_dir = Path(job.local_dir) / "results"
        sentinel = results_dir / _SENTINEL_NAME

        # Idempotency guard: fieldnotes log is not idempotent and both call
        # sites can fire more than once for one job (repeated RSYNC presses;
        # daemon plus manual sync). The sentinel makes re-invocation a no-op.
        if sentinel.exists():
            return False

        # Discover Fieldnotes run manifests: every directory at or below the
        # results dir that contains a params.json (a top-level one for a single
        # run, or one per task subdirectory for an array job).
        manifest_dirs = _discover_manifest_dirs(results_dir)
        if not manifest_dirs:
            return False

        cmd = [binary, "log"]
        cmd.append("--manifest")
        cmd.extend(str(d) for d in manifest_dirs)
        cmd.extend(["--slurm-job-id", job.job_id, "--tag", "clusterpilot"])
        if config.fieldnotes.project:
            cmd.extend(["--project", config.fieldnotes.project])

        proc = subprocess.run(
            cmd,
            cwd=job.local_dir,
            capture_output=True,
            timeout=_TIMEOUT,
            check=False,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or b"").decode(errors="replace").strip()
            log.warning(
                "fieldnotes log for job %s exited %d: %s",
                job.job_id, proc.returncode, stderr[-500:],
            )
            return False

        # Write the sentinel only on success, and only AFTER the fieldnotes call
        # so it can never be swept up as a run output by Fieldnotes' scan. A
        # failed attempt leaves no sentinel, so the next sync retries.
        try:
            sentinel.write_text(f"{job.job_id} {time.time()}\n")
        except OSError:
            pass  # swallowed like everything else; the log already landed

        return True
    except Exception:
        log.warning(
            "Fieldnotes logging failed for job %s — continuing",
            job.job_id, exc_info=True,
        )
        return False


def _discover_manifest_dirs(results_dir: Path) -> list[Path]:
    """Return the sorted directories containing a params.json at or below results_dir.

    Returns an empty list if the results dir does not exist or holds no manifest.
    """
    if not results_dir.is_dir():
        return []
    dirs = {p.parent for p in results_dir.rglob(_MANIFEST_NAME) if p.is_file()}
    return sorted(dirs)
