"""Tests for cluster/slurm.py — submit, status polling, log helpers."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from clusterpilot.cluster.slurm import (
    TERMINAL_STATES,
    SlurmError,
    find_log,
    job_status,
    submit,
    tail_log,
)
from clusterpilot.ssh.connection import SSHError


def _mock_run_remote(return_value: str) -> AsyncMock:
    return AsyncMock(return_value=return_value)


def _mock_run_remote_raises(exc: Exception) -> AsyncMock:
    m = AsyncMock(side_effect=exc)
    return m


# ── submit ────────────────────────────────────────────────────────────────────

class TestSubmit:
    async def test_returns_job_id_on_success(self):
        with patch(
            "clusterpilot.cluster.slurm.run_remote",
            _mock_run_remote("Submitted batch job 99123"),
        ):
            job_id = await submit("host", "user", "/home/user/job.sh")
        assert job_id == "99123"

    async def test_with_working_dir_prepends_cd(self):
        mock = _mock_run_remote("Submitted batch job 42")
        with patch("clusterpilot.cluster.slurm.run_remote", mock):
            job_id = await submit(
                "host", "user", "/home/user/job.sh", working_dir="/home/user/myproject"
            )
        assert job_id == "42"
        call_args = mock.call_args
        cmd = call_args[0][2]
        assert cmd.startswith("cd /home/user/myproject &&")
        assert "sbatch" in cmd

    async def test_raises_slurm_error_on_unexpected_output(self):
        with patch(
            "clusterpilot.cluster.slurm.run_remote",
            _mock_run_remote("sbatch: error: Batch job submission failed"),
        ):
            with pytest.raises(SlurmError, match="Unexpected sbatch output"):
                await submit("host", "user", "/home/user/job.sh")

    async def test_raises_slurm_error_when_ssh_fails(self):
        with patch(
            "clusterpilot.cluster.slurm.run_remote",
            _mock_run_remote_raises(SSHError("connection refused")),
        ):
            with pytest.raises(SlurmError, match="sbatch failed"):
                await submit("host", "user", "/home/user/job.sh")


# ── job_status ────────────────────────────────────────────────────────────────

class TestJobStatus:
    async def test_running_state_from_squeue(self):
        with patch(
            "clusterpilot.cluster.slurm.run_remote",
            _mock_run_remote("RUNNING"),
        ):
            state = await job_status("host", "user", "12345")
        assert state == "RUNNING"

    async def test_pending_state_from_squeue(self):
        with patch(
            "clusterpilot.cluster.slurm.run_remote",
            _mock_run_remote("PENDING"),
        ):
            state = await job_status("host", "user", "12345")
        assert state == "PENDING"

    async def test_falls_back_to_sacct_when_squeue_empty(self):
        # First call (squeue) returns empty, second (sacct) returns COMPLETED
        mock = AsyncMock(side_effect=["", "COMPLETED"])
        with patch("clusterpilot.cluster.slurm.run_remote", mock):
            state = await job_status("host", "user", "12345")
        assert state == "COMPLETED"

    async def test_sacct_cancelled_with_by_suffix(self):
        # "CANCELLED by 12345" should parse to "CANCELLED"
        mock = AsyncMock(side_effect=["", "CANCELLED by 12345"])
        with patch("clusterpilot.cluster.slurm.run_remote", mock):
            state = await job_status("host", "user", "12345")
        assert state == "CANCELLED"

    async def test_sacct_plus_suffix_stripped(self):
        # sacct sometimes appends "+" for aggregate records
        mock = AsyncMock(side_effect=["", "COMPLETED+"])
        with patch("clusterpilot.cluster.slurm.run_remote", mock):
            state = await job_status("host", "user", "12345")
        assert state == "COMPLETED"

    async def test_returns_none_when_both_fail(self):
        error = SSHError("no connection")
        mock = AsyncMock(side_effect=error)
        with patch("clusterpilot.cluster.slurm.run_remote", mock):
            state = await job_status("host", "user", "99999")
        assert state is None

    async def test_falls_back_to_sacct_when_squeue_raises(self):
        mock = AsyncMock(side_effect=[SSHError("no job"), "FAILED"])
        with patch("clusterpilot.cluster.slurm.run_remote", mock):
            state = await job_status("host", "user", "12345")
        assert state == "FAILED"


# ── TERMINAL_STATES ───────────────────────────────────────────────────────────

class TestTerminalStates:
    def test_expected_states_present(self):
        for state in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
            assert state in TERMINAL_STATES

    def test_active_states_absent(self):
        for state in ("PENDING", "RUNNING"):
            assert state not in TERMINAL_STATES


# ── tail_log ──────────────────────────────────────────────────────────────────

class TestTailLog:
    async def test_returns_output_on_success(self):
        with patch(
            "clusterpilot.cluster.slurm.run_remote",
            _mock_run_remote("line1\nline2\nline3"),
        ):
            result = await tail_log("host", "user", "/home/user/job.out")
        assert "line1" in result

    async def test_returns_empty_string_on_ssh_error(self):
        with patch(
            "clusterpilot.cluster.slurm.run_remote",
            _mock_run_remote_raises(SSHError("gone")),
        ):
            result = await tail_log("host", "user", "/home/user/job.out")
        assert result == ""


# ── find_log ──────────────────────────────────────────────────────────────────

class TestFindLog:
    async def test_finds_clusterpilot_default_path(self):
        # First candidate (<name>-<id>.out) exists
        mock = _mock_run_remote("exists")
        with patch("clusterpilot.cluster.slurm.run_remote", mock):
            path = await find_log("host", "user", "myjob", "99", "/home/user/myjob")
        assert path == "/home/user/myjob/myjob-99.out"

    async def test_falls_back_to_slurm_default_path(self):
        # First candidate missing, second (slurm-NNN.out) exists
        mock = AsyncMock(side_effect=["", "exists"])
        with patch("clusterpilot.cluster.slurm.run_remote", mock):
            path = await find_log("host", "user", "myjob", "99", "/home/user/myjob")
        assert path == "/home/user/myjob/slurm-99.out"

    async def test_returns_none_when_no_log_found(self):
        mock = _mock_run_remote("")
        with patch("clusterpilot.cluster.slurm.run_remote", mock):
            path = await find_log("host", "user", "myjob", "99", "/home/user/myjob")
        assert path is None
