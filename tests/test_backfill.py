"""Tests for jobs/backfill.py — recovering accounting for older finished jobs.

A job that finished before ClusterPilot recorded accounting has no core-hours,
and a usage report can only count what it was told. sacct still remembers, for
a while. These pin what one recovery pass does, and what it declines to do.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from clusterpilot.cluster.slurm import JobAccounting
from clusterpilot.config import ClusterProfile, Config, Defaults, HostedConfig
from clusterpilot.db import (
    JobRecord,
    get_job,
    get_jobs_missing_accounting,
    init_db,
    insert_job,
    update_accounting,
    update_status,
)
from clusterpilot.jobs.backfill import backfill_accounting

_ACCT = JobAccounting(
    cpus=4, gpus=1, nodes=1,
    runtime_seconds=3600, core_seconds=14400.0, gpu_seconds=3600.0,
    exit_code="0:0", tasks=1,
)


def _make_job(job_id: str = "12345", cluster: str = "grex", **kwargs) -> JobRecord:
    defaults = dict(
        job_id=job_id,
        job_name=f"job_{job_id}",
        cluster_name=cluster,
        host="yak.hpc.umanitoba.ca",
        user="juliaf",
        account="def-stamps",
        partition="stamps",
        script_path="/home/juliaf/jobs/j/job.sh",
        working_dir="/home/juliaf/jobs/j",
        local_dir="/home/juliaf/projects/j",
        walltime="08:00:00",
        status="COMPLETED",
        submitted_at=time.time(),
    )
    defaults.update(kwargs)
    return JobRecord(**defaults)


def _config(*names: str, api_token: str = "") -> Config:
    return Config(
        defaults=Defaults(),
        hosted=HostedConfig(api_token=api_token),
        clusters=[
            ClusterProfile(
                name=n, host=f"{n}.example.ca", user="juliaf",
                account="def-stamps", scratch="/scratch/juliaf",
            )
            for n in names
        ],
    )


@pytest.fixture
async def db_path(tmp_path):
    """A real on-disk database, since backfill opens its own connections."""
    path = tmp_path / "jobs.db"
    async with aiosqlite.connect(path) as db:
        await init_db(db)
    return path


async def _seed(path, *jobs: JobRecord) -> None:
    async with aiosqlite.connect(path) as db:
        await init_db(db)
        for job in jobs:
            await insert_job(db, job)


def _patched(found: dict[str, JobAccounting], *, connected: bool = True):
    """Patch out every remote call the backfill would make."""
    return (
        patch("clusterpilot.jobs.backfill.is_connected", return_value=connected),
        patch("clusterpilot.jobs.backfill.open_connection", MagicMock()),
        patch("clusterpilot.jobs.backfill.job_accounting_many",
              new=AsyncMock(return_value=found)),
        patch("clusterpilot.jobs.backfill.sync_job", new=AsyncMock(return_value=False)),
    )


async def _run(path, config, found, **kwargs):
    patches = _patched(found, connected=kwargs.pop("connected", True))
    for p in patches:
        p.start()
    try:
        return await backfill_accounting(config, path, **kwargs)
    finally:
        for p in patches:
            p.stop()


class TestSelection:
    async def test_a_finished_job_without_accounting_is_selected(self, db_path):
        await _seed(db_path, _make_job())
        async with aiosqlite.connect(db_path) as db:
            assert len(await get_jobs_missing_accounting(db)) == 1

    async def test_a_job_that_already_has_accounting_is_not(self, db_path):
        await _seed(db_path, _make_job())
        async with aiosqlite.connect(db_path) as db:
            await update_accounting(db, "12345", "grex", _ACCT)
            assert await get_jobs_missing_accounting(db) == []

    async def test_a_running_job_is_not(self, db_path):
        await _seed(db_path, _make_job(status="RUNNING"))
        async with aiosqlite.connect(db_path) as db:
            assert await get_jobs_missing_accounting(db) == []

    async def test_a_site_that_reports_no_cpus_is_not_asked_again(self, db_path):
        # runtime_seconds is the marker, so a job sacct answered about but
        # had no CPU count for still counts as done.
        await _seed(db_path, _make_job())
        async with aiosqlite.connect(db_path) as db:
            await update_accounting(db, "12345", "grex", JobAccounting(
                runtime_seconds=60, tasks=1,
            ))
            assert await get_jobs_missing_accounting(db) == []

    async def test_limit_and_cluster_narrow_the_selection(self, db_path):
        await _seed(
            db_path,
            _make_job("1", "grex", submitted_at=100.0),
            _make_job("2", "narval", submitted_at=200.0),
            _make_job("3", "narval", submitted_at=300.0),
        )
        async with aiosqlite.connect(db_path) as db:
            assert len(await get_jobs_missing_accounting(db, cluster_name="narval")) == 2
            newest = await get_jobs_missing_accounting(db, limit=1)
            assert [j.job_id for j in newest] == ["3"], "newest first"


class TestRecovery:
    async def test_stores_what_sacct_returned(self, db_path):
        await _seed(db_path, _make_job())
        report = await _run(db_path, _config("grex"), {"12345": _ACCT})

        assert report.considered == 1
        assert report.filled == 1
        async with aiosqlite.connect(db_path) as db:
            job = await get_job(db, "12345", "grex")
        assert job.core_seconds == 14400.0
        assert job.alloc_gpus == 1
        assert job.exit_code == "0:0"

    async def test_a_job_sacct_has_forgotten_is_counted_not_written(self, db_path):
        await _seed(db_path, _make_job())
        report = await _run(db_path, _config("grex"), {})

        assert report.filled == 0
        assert report.forgotten == 1
        async with aiosqlite.connect(db_path) as db:
            job = await get_job(db, "12345", "grex")
        assert job.core_seconds is None

    async def test_a_dry_run_writes_nothing_but_still_reports(self, db_path):
        await _seed(db_path, _make_job())
        report = await _run(db_path, _config("grex"), {"12345": _ACCT}, dry_run=True)

        assert report.filled == 1
        async with aiosqlite.connect(db_path) as db:
            job = await get_job(db, "12345", "grex")
        assert job.core_seconds is None, "dry run must not write"

    async def test_running_it_twice_is_a_no_op_the_second_time(self, db_path):
        await _seed(db_path, _make_job())
        await _run(db_path, _config("grex"), {"12345": _ACCT})
        second = await _run(db_path, _config("grex"), {"12345": _ACCT})
        assert second.considered == 0
        assert second.nothing_to_do

    async def test_nothing_to_do_on_an_empty_database(self, db_path):
        report = await _run(db_path, _config("grex"), {})
        assert report.nothing_to_do
        assert report.filled == 0


class TestClustersItCannotReach:
    async def test_a_cluster_missing_from_config_is_skipped_with_a_reason(self, db_path):
        await _seed(db_path, _make_job("1", "narval"))
        report = await _run(db_path, _config("grex"), {})
        assert report.skipped == {"narval": "not in config.toml"}
        assert report.filled == 0

    async def test_one_unreachable_cluster_does_not_stop_the_others(self, db_path):
        await _seed(db_path, _make_job("1", "grex"), _make_job("2", "narval"))

        from clusterpilot.ssh.connection import SSHError

        def _open(host, user):
            if host.startswith("narval"):
                raise SSHError("SSH to narval failed (exit 255)")

        with patch("clusterpilot.jobs.backfill.is_connected", return_value=False), \
             patch("clusterpilot.jobs.backfill.open_connection", side_effect=_open), \
             patch("clusterpilot.jobs.backfill.job_accounting_many",
                   new=AsyncMock(return_value={"1": _ACCT})), \
             patch("clusterpilot.jobs.backfill.sync_job", new=AsyncMock(return_value=False)):
            report = await backfill_accounting(_config("grex", "narval"), db_path)

        assert report.filled == 1
        assert "narval" in report.skipped
        async with aiosqlite.connect(db_path) as db:
            assert (await get_job(db, "1", "grex")).core_seconds == 14400.0

    async def test_connect_false_never_opens_a_connection(self, db_path):
        await _seed(db_path, _make_job())
        opener = MagicMock()
        with patch("clusterpilot.jobs.backfill.is_connected", return_value=False), \
             patch("clusterpilot.jobs.backfill.open_connection", opener), \
             patch("clusterpilot.jobs.backfill.job_accounting_many",
                   new=AsyncMock(return_value={})), \
             patch("clusterpilot.jobs.backfill.sync_job", new=AsyncMock(return_value=False)):
            report = await backfill_accounting(_config("grex"), db_path, connect=False)
        opener.assert_not_called()
        assert report.skipped == {"grex": "no SSH connection"}


class TestCloudSync:
    async def test_recovered_figures_are_pushed_to_the_dashboard(self, db_path):
        await _seed(db_path, _make_job())
        pusher = AsyncMock(return_value=True)
        with patch("clusterpilot.jobs.backfill.is_connected", return_value=True), \
             patch("clusterpilot.jobs.backfill.job_accounting_many",
                   new=AsyncMock(return_value={"12345": _ACCT})), \
             patch("clusterpilot.jobs.backfill.sync_job", new=pusher):
            report = await backfill_accounting(_config("grex", api_token="cp-abc"), db_path)

        assert report.synced == 1
        # The record handed to sync carries the recovered numbers, not nulls.
        pushed = pusher.await_args.args[0]
        assert pushed.core_seconds == 14400.0
        assert pushed.exit_code == "0:0"

    async def test_a_dry_run_pushes_nothing(self, db_path):
        await _seed(db_path, _make_job())
        pusher = AsyncMock(return_value=True)
        with patch("clusterpilot.jobs.backfill.is_connected", return_value=True), \
             patch("clusterpilot.jobs.backfill.job_accounting_many",
                   new=AsyncMock(return_value={"12345": _ACCT})), \
             patch("clusterpilot.jobs.backfill.sync_job", new=pusher):
            await backfill_accounting(
                _config("grex", api_token="cp-abc"), db_path, dry_run=True,
            )
        pusher.assert_not_awaited()

    async def test_a_sync_failure_does_not_lose_the_local_write(self, db_path):
        await _seed(db_path, _make_job())
        with patch("clusterpilot.jobs.backfill.is_connected", return_value=True), \
             patch("clusterpilot.jobs.backfill.job_accounting_many",
                   new=AsyncMock(return_value={"12345": _ACCT})), \
             patch("clusterpilot.jobs.backfill.sync_job",
                   new=AsyncMock(side_effect=OSError("no network"))):
            report = await backfill_accounting(_config("grex"), db_path)

        assert report.filled == 1
        assert report.synced == 0
        async with aiosqlite.connect(db_path) as db:
            assert (await get_job(db, "12345", "grex")).core_seconds == 14400.0
