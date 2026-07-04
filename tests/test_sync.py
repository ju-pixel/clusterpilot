"""Tests for jobs/sync.py — the hosted-tier state push.

The daemon's reconcile logic relies on ``sync_job`` returning True only when a
state actually landed in the cloud (HTTP < 400) and False otherwise, so it can
retry a missed transition on the next poll rather than assume success. These
tests pin that boolean contract.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from clusterpilot.config import HostedConfig
from clusterpilot.db import JobRecord
from clusterpilot.jobs.sync import sync_job


def _make_job(**kwargs) -> JobRecord:
    defaults = dict(
        job_id="12345",
        job_name="bench_run",
        cluster_name="grex",
        host="yak.hpc.umanitoba.ca",
        user="juliaf",
        account="def-stamps",
        partition="stamps",
        script_path="/home/juliaf/jobs/bench_run/job.sh",
        working_dir="/home/juliaf/jobs/bench_run",
        local_dir="/Users/juliaf/bench",
        walltime="14:00:00",
    )
    defaults.update(kwargs)
    return JobRecord(**defaults)


def _mock_http_client(status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "" if status_code < 400 else "boom"
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=resp)
    return client


class TestSyncJobReturn:
    async def test_returns_false_without_token(self):
        # Self-hosted users have no token; sync is a no-op and never "lands".
        result = await sync_job(_make_job(), "RUNNING", HostedConfig(api_token=""))
        assert result is False

    async def test_returns_true_on_success(self):
        client = _mock_http_client(200)
        with patch("clusterpilot.jobs.sync.httpx.AsyncClient", return_value=client):
            result = await sync_job(
                _make_job(), "RUNNING", HostedConfig(api_token="cp-abc")
            )
        assert result is True

    async def test_returns_false_on_error_status(self):
        client = _mock_http_client(500)
        with patch("clusterpilot.jobs.sync.httpx.AsyncClient", return_value=client):
            result = await sync_job(
                _make_job(), "RUNNING", HostedConfig(api_token="cp-abc")
            )
        assert result is False

    async def test_returns_false_on_network_error(self):
        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = AsyncMock(side_effect=OSError("connection refused"))
        with patch("clusterpilot.jobs.sync.httpx.AsyncClient", return_value=client):
            result = await sync_job(
                _make_job(), "COMPLETED", HostedConfig(api_token="cp-abc")
            )
        assert result is False
