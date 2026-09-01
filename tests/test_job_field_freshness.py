"""What the dashboard is told about a job while it is still running.

Two bugs with one shape: a job field was set once and never corrected.

#57 The partition came from scraping the generated script, with the literal
    string "skylake" as the fallback. A routed cluster's script carries no
    --partition directive by design, so every DRAC and Trillium job claimed to
    be in a partition none of them has.

#72 The per-task breakdown and the log tail only ever travelled to the hosted
    API with a status transition, so an array pushed "10R/60PD" at the instant
    it went RUNNING and never corrected it, however long it then ran. The local
    database was updated every poll, which is why the TUI was right throughout
    and only the web was wrong.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

from clusterpilot.cluster.slurm import JobAllocation, JobStatus, query_status
from clusterpilot.config import ClusterProfile, Config, Defaults, HostedConfig
from clusterpilot.db import JobRecord
from clusterpilot.jobs.daemon import TAIL_REFRESH_SECONDS, PollDaemon

_PROFILE = ClusterProfile(name="rorqual", host="rorqual.alliancecan.ca",
                          user="juliaf", account="def-stamps",
                          scratch="$SCRATCH", cluster_type="drac")


def _make_job(**kwargs) -> JobRecord:
    defaults = dict(
        job_id="20014027", job_name="zfc-field-cubic", cluster_name="rorqual",
        host="rorqual.alliancecan.ca", user="juliaf", account="def-stamps",
        partition="", script_path="/scratch/j/job.sh",
        working_dir="/scratch/j", local_dir="/local/j", walltime="24:00:00",
        status="RUNNING", started_at=1.0, log_path="/scratch/j/out.log",
        array_spec="0-69", status_detail="10R/60PD",
    )
    defaults.update(kwargs)
    return JobRecord(**defaults)


def _daemon() -> PollDaemon:
    config = Config(defaults=Defaults(), hosted=HostedConfig(api_token="cp-test"))
    return PollDaemon(config, db_path=":memory:")


async def _poll(daemon: PollDaemon, job: JobRecord, status: JobStatus) -> dict:
    """One _poll_job cycle with every remote call stubbed."""
    mocks = {"update_status": AsyncMock(), "sync": AsyncMock(),
             "tail_log": AsyncMock(return_value="line one\nline two")}
    with patch("clusterpilot.jobs.daemon.query_status",
               new=AsyncMock(return_value=status)), \
            patch("clusterpilot.jobs.daemon.update_status", new=mocks["update_status"]), \
            patch("clusterpilot.jobs.daemon.job_allocation",
                  new=AsyncMock(return_value=JobAllocation())), \
            patch("clusterpilot.jobs.daemon.update_allocation", new=AsyncMock()), \
            patch("clusterpilot.jobs.daemon.accumulate_reserved", new=AsyncMock()), \
            patch("clusterpilot.jobs.daemon.tail_log", new=mocks["tail_log"]), \
            patch.object(daemon, "_maybe_notify_running", new=AsyncMock()), \
            patch.object(daemon, "_sync", new=mocks["sync"]):
        await daemon._poll_job(MagicMock(), _PROFILE, job)
    return mocks


def _partition_writes(update_status: AsyncMock) -> list[str]:
    return [c.kwargs["partition"] for c in update_status.await_args_list
            if c.kwargs.get("partition") is not None]


class TestPartitionComesFromTheScheduler:
    async def test_squeue_partition_reaches_the_record(self):
        daemon = _daemon()
        job = _make_job(partition="")
        status = JobStatus(state="RUNNING", counts={"RUNNING": 10, "PENDING": 60},
                           source="squeue", partition="gpubase_bygpu_b3")

        mocks = await _poll(daemon, job, status)

        assert _partition_writes(mocks["update_status"]) == ["gpubase_bygpu_b3"]
        assert job.partition == "gpubase_bygpu_b3"

    async def test_a_wrong_stored_partition_is_corrected(self):
        """The case in the wild: every routed job stored "skylake"."""
        daemon = _daemon()
        job = _make_job(partition="skylake")
        status = JobStatus(state="RUNNING", counts={"RUNNING": 10},
                           source="squeue", partition="gpubase_bygpu_b3")

        mocks = await _poll(daemon, job, status)

        assert _partition_writes(mocks["update_status"]) == ["gpubase_bygpu_b3"]

    async def test_an_unchanged_partition_is_not_rewritten(self):
        daemon = _daemon()
        job = _make_job(partition="gpubase_bygpu_b3")
        status = JobStatus(state="RUNNING", counts={"RUNNING": 10},
                           source="squeue", partition="gpubase_bygpu_b3")

        mocks = await _poll(daemon, job, status)

        assert _partition_writes(mocks["update_status"]) == []

    async def test_sacct_reporting_no_partition_leaves_the_record_alone(self):
        """sacct's path carries no partition; it must not blank a good value.

        Polled in a settled terminal state rather than across the transition,
        so this exercises the partition rule alone.
        """
        daemon = _daemon()
        daemon._synced[f"{_PROFILE.name}:20014027"] = "COMPLETED"
        job = _make_job(partition="gpubase_bygpu_b3", status="COMPLETED",
                        status_detail="70C")
        status = JobStatus(state="COMPLETED", counts={"COMPLETED": 70},
                           source="sacct", partition="")

        mocks = await _poll(daemon, job, status)

        assert _partition_writes(mocks["update_status"]) == []
        assert job.partition == "gpubase_bygpu_b3"


class TestSqueueAsksForThePartition:
    async def test_the_partition_is_parsed_from_squeue(self):
        out = "20014027_[66-69]|PENDING|gpubase_bygpu_b3\n20014027_10|RUNNING|gpubase_bygpu_b3"
        with patch("clusterpilot.cluster.slurm.run_remote",
                   new=AsyncMock(return_value=out)):
            status = await query_status("h", "u", "20014027")

        assert status is not None
        assert status.partition == "gpubase_bygpu_b3"
        assert status.counts == {"PENDING": 4, "RUNNING": 1}

    async def test_a_missing_partition_column_is_not_read_as_one(self):
        """Empty fields must not shift the state column into the partition."""
        out = "20014027_1|RUNNING|"
        with patch("clusterpilot.cluster.slurm.run_remote",
                   new=AsyncMock(return_value=out)):
            status = await query_status("h", "u", "20014027")

        assert status is not None
        assert status.partition == ""
        assert status.counts == {"RUNNING": 1}


class TestTheBreakdownKeepsReachingTheDashboard:
    async def test_a_changed_breakdown_syncs_without_a_transition(self):
        """The #72 bug: this sync never happened, so the web froze at start."""
        daemon = _daemon()
        daemon._synced[f"{_PROFILE.name}:20014027"] = "RUNNING"
        job = _make_job(status_detail="10R/60PD")
        status = JobStatus(state="RUNNING", counts={"RUNNING": 66, "PENDING": 4},
                           source="squeue", partition="gpubase_bygpu_b3")

        mocks = await _poll(daemon, job, status)

        mocks["sync"].assert_awaited()
        assert job.status_detail == "66R/4PD"

    async def test_an_unchanged_breakdown_does_not_resync(self):
        """Otherwise every poll of every idle job becomes an HTTP request."""
        daemon = _daemon()
        key = f"{_PROFILE.name}:20014027"
        daemon._synced[key] = "RUNNING"
        daemon._tailed[key] = time.time()
        job = _make_job(status_detail="10R/60PD")
        status = JobStatus(state="RUNNING", counts={"RUNNING": 10, "PENDING": 60},
                           source="squeue", partition="")

        mocks = await _poll(daemon, job, status)

        mocks["sync"].assert_not_awaited()

    async def test_nothing_is_pushed_when_the_hosted_tier_is_off(self):
        daemon = PollDaemon(Config(defaults=Defaults()), db_path=":memory:")
        job = _make_job(status_detail="10R/60PD")
        status = JobStatus(state="RUNNING", counts={"RUNNING": 66, "PENDING": 4},
                           source="squeue", partition="")

        mocks = await _poll(daemon, job, status)

        mocks["sync"].assert_not_awaited()


class TestTheLogTailRefreshesOnAClock:
    async def test_a_stale_tail_is_refreshed(self):
        daemon = _daemon()
        key = f"{_PROFILE.name}:20014027"
        daemon._synced[key] = "RUNNING"
        daemon._tailed[key] = time.time() - TAIL_REFRESH_SECONDS - 1
        job = _make_job()
        status = JobStatus(state="RUNNING", counts={"RUNNING": 10, "PENDING": 60},
                           source="squeue", partition="")

        mocks = await _poll(daemon, job, status)

        mocks["tail_log"].assert_awaited()
        assert mocks["sync"].await_args.kwargs["log_tail"]

    async def test_a_fresh_tail_is_left_alone(self):
        """One SSH round trip per poll per job is what this avoids."""
        daemon = _daemon()
        key = f"{_PROFILE.name}:20014027"
        daemon._synced[key] = "RUNNING"
        daemon._tailed[key] = time.time()
        job = _make_job()
        status = JobStatus(state="RUNNING", counts={"RUNNING": 10, "PENDING": 60},
                           source="squeue", partition="")

        mocks = await _poll(daemon, job, status)

        mocks["tail_log"].assert_not_awaited()

    async def test_a_pending_job_is_not_tailed(self):
        daemon = _daemon()
        key = f"{_PROFILE.name}:20014027"
        daemon._synced[key] = "PENDING"
        job = _make_job(status="PENDING", started_at=None)
        status = JobStatus(state="PENDING", counts={"PENDING": 70},
                           source="squeue", partition="")

        mocks = await _poll(daemon, job, status)

        mocks["tail_log"].assert_not_awaited()

    def test_the_refresh_interval_is_slower_than_the_poll_cycle(self):
        """The point is that the log stops being frozen, not that it is live."""
        assert TAIL_REFRESH_SECONDS >= 60
