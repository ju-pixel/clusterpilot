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


class TestSyncPayloadAccounting:
    """The dashboard can only show what the daemon actually sends."""

    async def _payload(self, job: JobRecord) -> dict:
        client = _mock_http_client(200)
        with patch("clusterpilot.jobs.sync.httpx.AsyncClient", return_value=client):
            await sync_job(job, "COMPLETED", HostedConfig(api_token="cp-abc"))
        return client.post.await_args.kwargs["json"]

    async def test_carries_what_the_tui_already_knew(self):
        payload = await self._payload(_make_job(
            account="def-stamps",
            array_spec="0-99",
            status_detail="5R/27PD",
            efficiency="CPU 12%, mem 6% of 16 GB",
        ))
        assert payload["account"] == "def-stamps"
        assert payload["array_spec"] == "0-99"
        assert payload["status_detail"] == "5R/27PD"
        assert payload["efficiency"] == "CPU 12%, mem 6% of 16 GB"

    async def test_carries_the_accounting_numbers(self):
        payload = await self._payload(_make_job(
            alloc_cpus=4, alloc_gpus=1, alloc_nodes=1,
            runtime_seconds=3600, core_seconds=14400.0, gpu_seconds=3600.0,
            exit_code="0:0",
        ))
        assert payload["alloc_cpus"] == 4
        assert payload["alloc_gpus"] == 1
        assert payload["alloc_nodes"] == 1
        assert payload["runtime_seconds"] == 3600
        assert payload["core_seconds"] == 14400.0
        assert payload["gpu_seconds"] == 3600.0
        assert payload["exit_code"] == "0:0"

    async def test_unknown_accounting_travels_as_null_not_zero(self):
        # A report that reads a missing figure as zero under-counts silently.
        payload = await self._payload(_make_job())
        for field in ("alloc_cpus", "alloc_gpus", "alloc_nodes",
                      "runtime_seconds", "core_seconds", "gpu_seconds"):
            assert payload[field] is None, field

    async def test_empty_strings_travel_as_null(self):
        payload = await self._payload(_make_job(account="", array_spec=""))
        assert payload["account"] is None
        assert payload["array_spec"] is None


class TestSyncPayloadProvenance:
    """A measured figure must reach the dashboard labelled as measured."""

    async def _payload(self, job: JobRecord) -> dict:
        client = _mock_http_client(200)
        with patch("clusterpilot.jobs.sync.httpx.AsyncClient", return_value=client):
            await sync_job(job, "COMPLETED", HostedConfig(api_token="cp-abc"))
        return client.post.await_args.kwargs["json"]

    async def test_billing_travels(self):
        payload = await self._payload(_make_job(
            alloc_billing=16000, billing_seconds=57_600_000.0,
        ))
        assert payload["alloc_billing"] == 16000
        assert payload["billing_seconds"] == 57_600_000.0

    async def test_the_source_travels(self):
        assert (await self._payload(
            _make_job(accounting_source="measured")
        ))["accounting_source"] == "measured"
        assert (await self._payload(
            _make_job(accounting_source="sacct")
        ))["accounting_source"] == "sacct"

    async def test_an_unaccounted_job_sends_no_source(self):
        assert (await self._payload(_make_job()))["accounting_source"] is None
