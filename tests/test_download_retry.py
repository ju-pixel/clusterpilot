"""Retrying a results download that failed (issue #48).

A job is written terminal the moment it finishes, so it drops out of
get_active_jobs and the ordinary poll never looks at it again. Before this, a
single failed rsync at 03:00 left the results on the cluster with nothing but
"SYNCED no" on the jobs screen to say so.

The subtlety worth pinning: `synced = 0` is also true of a job that failed
before producing anything and never wanted a download, so the attempt count
is what separates the two.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from clusterpilot.db import (
    JobRecord,
    get_retryable_downloads,
    init_db,
    insert_job,
    record_download_attempt,
    update_status,
)


def _make_job(job_id="12345", status="COMPLETED", **kwargs) -> JobRecord:
    defaults = dict(
        job_id=job_id, job_name="sweep", cluster_name="grex",
        host="grex.hpc.umanitoba.ca", user="juliaf", account="def-stamps",
        partition="compute", script_path="/s.sh", working_dir="/w",
        local_dir="/l", walltime="08:00:00", status=status,
        submitted_at=time.time(),
    )
    defaults.update(kwargs)
    return JobRecord(**defaults)


@pytest.fixture
async def db():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        yield conn


class TestWhatCountsAsRetryable:
    async def test_a_failed_download_is_retried(self, db):
        await insert_job(db, _make_job())
        await record_download_attempt(db, "12345", "grex", synced=False)
        assert [j.job_id for j in await get_retryable_downloads(db)] == ["12345"]

    async def test_a_successful_download_is_not(self, db):
        await insert_job(db, _make_job())
        await record_download_attempt(db, "12345", "grex", synced=True)
        assert await get_retryable_downloads(db) == []

    async def test_a_job_that_never_wanted_results_is_not(self, db):
        # The heart of it: a job that failed before producing anything also has
        # synced = 0, and rsyncing it would fetch nothing, every poll, forever.
        await insert_job(db, _make_job(status="FAILED"))
        assert await get_retryable_downloads(db) == []

    async def test_a_running_job_is_not(self, db):
        await insert_job(db, _make_job(status="RUNNING"))
        await record_download_attempt(db, "12345", "grex", synced=False)
        assert await get_retryable_downloads(db) == []

    async def test_it_gives_up_after_the_cap(self, db):
        await insert_job(db, _make_job())
        for _ in range(5):
            await record_download_attempt(db, "12345", "grex", synced=False)
        assert await get_retryable_downloads(db) == []

    async def test_it_keeps_trying_below_the_cap(self, db):
        await insert_job(db, _make_job())
        for n in range(1, 5):
            await record_download_attempt(db, "12345", "grex", synced=False)
            assert len(await get_retryable_downloads(db)) == 1, f"attempt {n}"

    async def test_a_cleaned_remote_is_not_retried(self, db):
        # Nothing left to fetch, so retrying can only fail.
        from clusterpilot.db import mark_remote_cleaned
        await insert_job(db, _make_job())
        await record_download_attempt(db, "12345", "grex", synced=False)
        await mark_remote_cleaned(db, "12345", "grex")
        assert await get_retryable_downloads(db) == []

    async def test_a_later_success_clears_it(self, db):
        await insert_job(db, _make_job())
        await record_download_attempt(db, "12345", "grex", synced=False)
        await record_download_attempt(db, "12345", "grex", synced=True)
        assert await get_retryable_downloads(db) == []
        async with db.execute("SELECT synced FROM jobs WHERE job_id='12345'") as cur:
            assert (await cur.fetchone())[0] == 1


class TestTheDaemonPass:
    def _daemon(self, tmp_path):
        from clusterpilot.config import ClusterProfile, Config, Defaults
        from clusterpilot.jobs.daemon import PollDaemon
        cfg = Config(defaults=Defaults(), clusters=[ClusterProfile(
            name="grex", host="grex.hpc.umanitoba.ca", user="juliaf",
            account="def-stamps", scratch="/scratch",
        )])
        return PollDaemon(cfg, tmp_path / "jobs.db")

    async def _seed(self, path):
        async with aiosqlite.connect(path) as db:
            await init_db(db)
            await insert_job(db, _make_job())
            await record_download_attempt(db, "12345", "grex", synced=False)

    async def test_a_reachable_cluster_is_retried_and_the_job_clears(self, tmp_path):
        daemon = self._daemon(tmp_path)
        await self._seed(daemon.db_path)
        with patch("clusterpilot.jobs.daemon.is_connected", return_value=True), \
             patch.object(daemon, "_download_results", new=AsyncMock(return_value=True)) as dl, \
             patch.object(daemon, "_sync", new=AsyncMock()), \
             patch("clusterpilot.jobs.daemon.log_completed_job", new=MagicMock()):
            await daemon._retry_downloads()
        dl.assert_awaited_once()
        async with aiosqlite.connect(daemon.db_path) as db:
            assert await get_retryable_downloads(db) == []

    async def test_an_unreachable_cluster_is_left_for_next_time(self, tmp_path):
        daemon = self._daemon(tmp_path)
        await self._seed(daemon.db_path)
        with patch("clusterpilot.jobs.daemon.is_connected", return_value=False), \
             patch.object(daemon, "_download_results", new=AsyncMock()) as dl:
            await daemon._retry_downloads()
        dl.assert_not_awaited()
        async with aiosqlite.connect(daemon.db_path) as db:
            # Not counted as an attempt, so the budget is not burned by an
            # outage the job had nothing to do with.
            assert len(await get_retryable_downloads(db)) == 1

    async def test_fieldnotes_is_only_told_once_the_results_arrive(self, tmp_path):
        daemon = self._daemon(tmp_path)
        await self._seed(daemon.db_path)
        logger = MagicMock()
        with patch("clusterpilot.jobs.daemon.is_connected", return_value=True), \
             patch.object(daemon, "_download_results", new=AsyncMock(return_value=False)), \
             patch.object(daemon, "_sync", new=AsyncMock()), \
             patch("clusterpilot.jobs.daemon.log_completed_job", new=logger):
            await daemon._retry_downloads()
        logger.assert_not_called()

    async def test_a_failure_in_the_pass_never_escapes(self, tmp_path):
        daemon = self._daemon(tmp_path)
        await self._seed(daemon.db_path)
        with patch("clusterpilot.jobs.daemon.is_connected", return_value=True), \
             patch.object(daemon, "_download_results",
                          new=AsyncMock(side_effect=RuntimeError("boom"))):
            await daemon._retry_downloads()   # must not raise
