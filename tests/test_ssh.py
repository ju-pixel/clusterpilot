"""Tests for ssh/connection.py — ControlMaster wrappers.

Subprocess and asyncio.create_subprocess_exec are mocked throughout;
no real SSH connections are made.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clusterpilot.ssh.connection import SSHError, is_connected, run_remote


# ── is_connected ──────────────────────────────────────────────────────────────

class TestIsConnected:
    def test_returns_true_when_socket_alive(self):
        proc = MagicMock()
        proc.returncode = 0
        with patch("clusterpilot.ssh.connection.subprocess.run", return_value=proc):
            assert is_connected("grex.example.com", "juliaf") is True

    def test_returns_false_when_no_socket(self):
        proc = MagicMock()
        proc.returncode = 1
        with patch("clusterpilot.ssh.connection.subprocess.run", return_value=proc):
            assert is_connected("grex.example.com", "juliaf") is False

    def test_passes_check_flag_to_ssh(self):
        proc = MagicMock()
        proc.returncode = 0
        with patch("clusterpilot.ssh.connection.subprocess.run", return_value=proc) as mock_run:
            is_connected("grex.example.com", "juliaf")

        args = mock_run.call_args[0][0]
        assert "-O" in args
        assert "check" in args

    def test_includes_user_at_host(self):
        proc = MagicMock()
        proc.returncode = 0
        with patch("clusterpilot.ssh.connection.subprocess.run", return_value=proc) as mock_run:
            is_connected("grex.example.com", "juliaf")

        args = mock_run.call_args[0][0]
        assert "juliaf@grex.example.com" in args


# ── run_remote ────────────────────────────────────────────────────────────────

def _make_proc(returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    return proc


class TestRunRemote:
    async def test_returns_stripped_stdout_on_success(self):
        proc = _make_proc(0, stdout=b"  hello world\n  ")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await run_remote("host", "user", "echo hello")
        assert result == "hello world"

    async def test_raises_ssh_error_on_nonzero_exit(self):
        proc = _make_proc(1, stderr=b"Permission denied")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            with pytest.raises(SSHError, match="Remote command failed"):
                await run_remote("host", "user", "bad_command")

    async def test_error_message_includes_stderr(self):
        proc = _make_proc(255, stderr=b"Connection refused")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            with pytest.raises(SSHError, match="Connection refused"):
                await run_remote("host", "user", "cmd")

    async def test_raises_ssh_error_on_timeout(self):
        import asyncio

        call_count = 0

        async def communicate():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: block forever so wait_for times out.
                await asyncio.sleep(999)
            # Second call (reap after kill): return immediately.
            return b"", b""

        proc = MagicMock()
        proc.returncode = None
        proc.kill = MagicMock()
        proc.communicate = communicate

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            with pytest.raises(SSHError, match="timed out"):
                await run_remote("host", "user", "slow_cmd", timeout=0.01)

    async def test_uses_batch_mode_yes(self):
        proc = _make_proc(0, stdout=b"ok")
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=proc)
        ) as mock_exec:
            await run_remote("host", "user", "cmd")

        args = mock_exec.call_args[0]
        assert "BatchMode=yes" in " ".join(str(a) for a in args)

    async def test_never_becomes_new_master(self):
        proc = _make_proc(0, stdout=b"ok")
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=proc)
        ) as mock_exec:
            await run_remote("host", "user", "cmd")

        args = " ".join(str(a) for a in mock_exec.call_args[0])
        assert "ControlMaster=no" in args
