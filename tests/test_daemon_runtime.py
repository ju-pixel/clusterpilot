"""How long a job ran, written down rather than only remembered.

Issue #47: sacct cannot reach slurmdbd from an Alliance login node, so on the
clusters ClusterPilot is mostly used on nothing comes back to store when a job
ends. The daemon already knew the answer from its own clock, but only set it on
the JobRecord in memory, so the figure travelled to the dashboard on the one
sync that followed the terminal transition and was gone from the local database
by the next restart. These tests go through the real SQLite writes rather than
a mocked ``update_status``, because the whole point is that the row survives.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from clusterpilot.cluster.slurm import JobAccounting, JobStatus
from clusterpilot.config import ClusterProfile, Config, Defaults
from clusterpilot.db import JobRecord, get_job, init_db, insert_job, update_status
from clusterpilot.jobs.daemon import PollDaemon

_PROFILE = ClusterProfile(name="narval", host="narval.alliancecan.ca",
                          user="juliaf", account="def-stamps",
                          scratch="$SCRATCH", cluster_type="drac")

_AN_HOUR = 3600


def _make_job(**kwargs) -> JobRecord:
    defaults = dict(
        job_id="1894814", job_name="zfc-sweep", cluster_name="narval",
        host="narval.alliancecan.ca", user="juliaf", account="def-stamps",
        partition="", script_path="/scratch/j/job.sh",
        working_dir="/scratch/j", local_dir="/local/j", walltime="08:00:00",
        status="RUNNING", submitted_at=time.time() - 2 * _AN_HOUR,
        started_at=time.time() - _AN_HOUR,
    )
    defaults.update(kwargs)
    return JobRecord(**defaults)


@pytest.fixture
async def db():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        yield conn


async def _finish(
    db: aiosqlite.Connection,
    job: JobRecord,
    acct: JobAccounting,
    *,
    state: str = "COMPLETED",
) -> JobRecord:
    """Drive one terminal transition with only the remote calls stubbed."""
    daemon = PollDaemon(Config(defaults=Defaults()), db_path=":memory:")
    status = JobStatus(state=state, counts={state: 1}, source="squeue")
    with patch.object(daemon, "_job_efficiency", new=AsyncMock(return_value="")), \
            patch.object(daemon, "_job_accounting", new=AsyncMock(return_value=acct)), \
            patch.object(daemon, "_sync_and_notify_completed", new=AsyncMock()), \
            patch.object(daemon, "_sync_and_notify_partial", new=AsyncMock()), \
            patch.object(daemon, "_notify_failed", new=AsyncMock()):
        await daemon._handle_transition(db, _PROFILE, job, status)
    stored = await get_job(db, job.job_id, job.cluster_name)
    assert stored is not None
    return stored


class TestTheMeasuredDurationIsPersisted:
    async def test_a_site_without_sacct_still_records_how_long_the_job_ran(self, db):
        job = _make_job()
        await insert_job(db, job)

        stored = await _finish(db, job, JobAccounting())

        # Wall clock from started_at to the transition, to within the moment
        # the test itself takes.
        assert stored.runtime_seconds == pytest.approx(_AN_HOUR, abs=5)
        # And the in-memory record still agrees with the row.
        assert job.runtime_seconds == stored.runtime_seconds

    async def test_a_failed_job_records_it_too(self, db):
        job = _make_job()
        await insert_job(db, job)

        stored = await _finish(db, job, JobAccounting(), state="FAILED")

        assert stored.runtime_seconds == pytest.approx(_AN_HOUR, abs=5)

    async def test_a_job_that_never_started_records_nothing(self, db):
        """A cancelled-while-queued job has no duration to invent."""
        job = _make_job(status="PENDING", started_at=None)
        await insert_job(db, job)

        stored = await _finish(db, job, JobAccounting(), state="CANCELLED")

        assert stored.runtime_seconds is None


class TestSacctStaysAuthoritative:
    async def test_the_accounting_figure_wins_over_the_measured_one(self, db):
        """sacct's duration is the job's, not the daemon's view of the job's.

        The two writes land in order in ``_handle_transition``; this is the
        test that catches a reordering of them.
        """
        job = _make_job()
        await insert_job(db, job)

        stored = await _finish(db, job, JobAccounting(
            cpus=4, runtime_seconds=1234, core_seconds=4936.0, tasks=1,
        ))

        assert stored.runtime_seconds == 1234
        assert stored.accounting_source == "sacct"
        assert job.runtime_seconds == 1234

    async def test_a_duration_already_recorded_is_left_alone(self, db):
        """Whatever put a figure there knew more than a wall-clock subtraction."""
        job = _make_job(runtime_seconds=99)
        await insert_job(db, job)
        await update_status(db, job.job_id, job.cluster_name, "RUNNING",
                            runtime_seconds=99)

        stored = await _finish(db, job, JobAccounting())

        assert stored.runtime_seconds == 99
        assert job.runtime_seconds == 99
