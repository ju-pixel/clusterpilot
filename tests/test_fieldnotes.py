"""Tests for jobs/fieldnotes.py — best-effort local Fieldnotes logging.

The helper is a fire-and-forget layer modelled on jobs/sync.py: off by default,
a silent no-op when disabled / the binary is absent / no params.json is present,
and it never raises. These tests pin the argv it builds, the no-op gates, the
sentinel-based idempotency, and that nothing ever propagates.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from clusterpilot.config import Config, Defaults, FieldnotesConfig
from clusterpilot.db import JobRecord
from clusterpilot.jobs.fieldnotes import log_completed_job

_FIELDNOTES_BIN = "/usr/bin/fieldnotes"


def _make_job(local_dir: str, **kwargs) -> JobRecord:
    defaults = dict(
        job_id="12345",
        job_name="bench_run",
        cluster_name="grex",
        host="yak.hpc.umanitoba.ca",
        user="juliaf",
        account="def-stamps",
        partition="stamps",
        script_path=f"{local_dir}/job.sh",
        working_dir="/home/juliaf/jobs/bench_run",
        local_dir=local_dir,
        walltime="14:00:00",
    )
    defaults.update(kwargs)
    return JobRecord(**defaults)


def _make_config(enabled: bool = True, project: str = "") -> Config:
    return Config(
        defaults=Defaults(),
        fieldnotes=FieldnotesConfig(enabled=enabled, project=project),
    )


def _write_manifest(directory: Path, **params) -> None:
    """Write a params.json into `directory` (created if needed)."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "params.json").write_text('{"L": 128}')


def _run_result(returncode: int = 0, stderr: bytes = b"") -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stderr = stderr
    return result


# ── argv construction ─────────────────────────────────────────────────────────

class TestArgvConstruction:
    def test_single_manifest_argv_and_cwd(self, tmp_path):
        results = tmp_path / "results"
        _write_manifest(results)
        job = _make_job(str(tmp_path))

        with patch("clusterpilot.jobs.fieldnotes.shutil.which", return_value=_FIELDNOTES_BIN), \
             patch("clusterpilot.jobs.fieldnotes.subprocess.run", return_value=_run_result()) as run:
            result = log_completed_job(job, _make_config())

        assert result is True
        args, kwargs = run.call_args
        assert args[0] == [
            _FIELDNOTES_BIN, "log",
            "--manifest", str(results),
            "--slurm-job-id", "12345",
            "--tag", "clusterpilot",
        ]
        assert kwargs["cwd"] == str(tmp_path)

    def test_array_dirs_collapse_into_one_invocation(self, tmp_path):
        results = tmp_path / "results"
        _write_manifest(results / "task_0")
        _write_manifest(results / "task_1")
        job = _make_job(str(tmp_path))

        with patch("clusterpilot.jobs.fieldnotes.shutil.which", return_value=_FIELDNOTES_BIN), \
             patch("clusterpilot.jobs.fieldnotes.subprocess.run", return_value=_run_result()) as run:
            result = log_completed_job(job, _make_config())

        assert result is True
        assert run.call_count == 1
        argv = run.call_args[0][0]
        # Both task dirs are passed as --manifest paths in a single call.
        assert argv.count("--manifest") == 1
        assert str(results / "task_0") in argv
        assert str(results / "task_1") in argv

    def test_project_appended_when_set(self, tmp_path):
        _write_manifest(tmp_path / "results")
        job = _make_job(str(tmp_path))

        with patch("clusterpilot.jobs.fieldnotes.shutil.which", return_value=_FIELDNOTES_BIN), \
             patch("clusterpilot.jobs.fieldnotes.subprocess.run", return_value=_run_result()) as run:
            log_completed_job(job, _make_config(project="spin-glass"))

        argv = run.call_args[0][0]
        assert argv[-2:] == ["--project", "spin-glass"]

    def test_project_absent_when_empty(self, tmp_path):
        _write_manifest(tmp_path / "results")
        job = _make_job(str(tmp_path))

        with patch("clusterpilot.jobs.fieldnotes.shutil.which", return_value=_FIELDNOTES_BIN), \
             patch("clusterpilot.jobs.fieldnotes.subprocess.run", return_value=_run_result()) as run:
            log_completed_job(job, _make_config(project=""))

        assert "--project" not in run.call_args[0][0]


# ── no-op gates ───────────────────────────────────────────────────────────────

class TestNoOpGates:
    def test_disabled_config(self, tmp_path):
        _write_manifest(tmp_path / "results")
        job = _make_job(str(tmp_path))
        with patch("clusterpilot.jobs.fieldnotes.subprocess.run") as run:
            result = log_completed_job(job, _make_config(enabled=False))
        assert result is False
        run.assert_not_called()

    def test_binary_absent(self, tmp_path):
        _write_manifest(tmp_path / "results")
        job = _make_job(str(tmp_path))
        with patch("clusterpilot.jobs.fieldnotes.shutil.which", return_value=None), \
             patch("clusterpilot.jobs.fieldnotes.subprocess.run") as run:
            result = log_completed_job(job, _make_config())
        assert result is False
        run.assert_not_called()

    def test_no_manifest_present(self, tmp_path):
        (tmp_path / "results").mkdir()  # results dir exists but has no params.json
        job = _make_job(str(tmp_path))
        with patch("clusterpilot.jobs.fieldnotes.shutil.which", return_value=_FIELDNOTES_BIN), \
             patch("clusterpilot.jobs.fieldnotes.subprocess.run") as run:
            result = log_completed_job(job, _make_config())
        assert result is False
        run.assert_not_called()

    def test_missing_results_dir(self, tmp_path):
        job = _make_job(str(tmp_path))  # no results/ at all
        with patch("clusterpilot.jobs.fieldnotes.shutil.which", return_value=_FIELDNOTES_BIN), \
             patch("clusterpilot.jobs.fieldnotes.subprocess.run") as run:
            result = log_completed_job(job, _make_config())
        assert result is False
        run.assert_not_called()

    def test_sentinel_present(self, tmp_path):
        results = tmp_path / "results"
        _write_manifest(results)
        (results / ".fieldnotes-logged").write_text("12345 0\n")
        job = _make_job(str(tmp_path))
        with patch("clusterpilot.jobs.fieldnotes.shutil.which", return_value=_FIELDNOTES_BIN), \
             patch("clusterpilot.jobs.fieldnotes.subprocess.run") as run:
            result = log_completed_job(job, _make_config())
        assert result is False
        run.assert_not_called()


# ── sentinel lifecycle ────────────────────────────────────────────────────────

class TestSentinelLifecycle:
    def test_success_writes_sentinel_and_second_call_noops(self, tmp_path):
        results = tmp_path / "results"
        _write_manifest(results)
        job = _make_job(str(tmp_path))
        sentinel = results / ".fieldnotes-logged"

        with patch("clusterpilot.jobs.fieldnotes.shutil.which", return_value=_FIELDNOTES_BIN), \
             patch("clusterpilot.jobs.fieldnotes.subprocess.run", return_value=_run_result()) as run:
            first = log_completed_job(job, _make_config())
            assert first is True
            assert sentinel.exists()

            second = log_completed_job(job, _make_config())

        assert second is False
        assert run.call_count == 1  # second call short-circuited on the sentinel

    def test_failure_leaves_no_sentinel_and_retries(self, tmp_path):
        results = tmp_path / "results"
        _write_manifest(results)
        job = _make_job(str(tmp_path))
        sentinel = results / ".fieldnotes-logged"

        with patch("clusterpilot.jobs.fieldnotes.shutil.which", return_value=_FIELDNOTES_BIN), \
             patch("clusterpilot.jobs.fieldnotes.subprocess.run",
                   return_value=_run_result(returncode=1, stderr=b"boom")) as run:
            result = log_completed_job(job, _make_config())
            assert result is False
            assert not sentinel.exists()  # no sentinel on failure

            # A subsequent sync retries because nothing marked it done.
            log_completed_job(job, _make_config())

        assert run.call_count == 2


# ── nothing propagates ────────────────────────────────────────────────────────

class TestNeverRaises:
    def test_subprocess_raises_is_swallowed(self, tmp_path):
        _write_manifest(tmp_path / "results")
        job = _make_job(str(tmp_path))
        with patch("clusterpilot.jobs.fieldnotes.shutil.which", return_value=_FIELDNOTES_BIN), \
             patch("clusterpilot.jobs.fieldnotes.subprocess.run",
                   side_effect=OSError("no such binary")):
            result = log_completed_job(job, _make_config())
        assert result is False

    def test_timeout_is_swallowed(self, tmp_path):
        import subprocess
        _write_manifest(tmp_path / "results")
        job = _make_job(str(tmp_path))
        with patch("clusterpilot.jobs.fieldnotes.shutil.which", return_value=_FIELDNOTES_BIN), \
             patch("clusterpilot.jobs.fieldnotes.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="fieldnotes", timeout=30)):
            result = log_completed_job(job, _make_config())
        assert result is False
