"""Array-aware polling in the daemon (issues #1, #2 and #27).

Drives PollDaemon._poll_job with query_status stubbed, so each test pins one
contract about how a job array's aggregate state is acted upon: a squeue outage
must not declare a half-finished array complete, a second RUNNING transition
must not re-notify, a mixed terminal array must download its results and then
report the failure, and an array's per-task logs must be found at all.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from clusterpilot.cluster.slurm import JobAccounting, JobAllocation, JobStatus
from clusterpilot.config import ClusterProfile, Config, Defaults
from clusterpilot.db import JobRecord
from clusterpilot.jobs.daemon import PollDaemon

_PROFILE = ClusterProfile(name="grex", host="yak.hpc.umanitoba.ca", user="juliaf",
                          account="def-stamps", scratch="$HOME/jobs")


def _make_job(**kwargs) -> JobRecord:
    defaults = dict(
        job_id="12345",
        job_name="bench_run",
        cluster_name="grex",
        host="yak.hpc.umanitoba.ca",
        user="juliaf",
        account="def-stamps",
        partition="stamps",
        script_path="/local/bench/job.sh",
        working_dir="/home/juliaf/jobs/bench_run",
        local_dir="/local/bench",
        walltime="14:00:00",
    )
    defaults.update(kwargs)
    return JobRecord(**defaults)


def _make_daemon() -> PollDaemon:
    return PollDaemon(Config(defaults=Defaults()), db_path=":memory:")


async def _poll(
    job: JobRecord,
    status: JobStatus,
    array_logs: dict[str, str] | None = None,
    tails: dict[str, str] | None = None,
) -> dict[str, MagicMock]:
    """Run one _poll_job cycle with every remote call stubbed out."""
    daemon = _make_daemon()

    async def _tail(host: str, user: str, path: str) -> str:
        return (tails or {}).get(path, "")

    mocks = {
        "update_status": AsyncMock(),
        "download": AsyncMock(),
        "notify_started": AsyncMock(),
        "notify_completed": AsyncMock(),
        "notify_failed": AsyncMock(),
        "find_log": AsyncMock(return_value="/home/juliaf/jobs/bench_run/out"),
        "find_array_logs": AsyncMock(return_value=dict(array_logs or {})),
        "tail_log": AsyncMock(side_effect=_tail),
        "log_completed_job": MagicMock(),
        # seff and sacct both run at every terminal transition; never let a
        # test reach SSH.
        "job_efficiency": AsyncMock(return_value=""),
        "job_accounting": AsyncMock(return_value=JobAccounting()),
        "update_accounting": AsyncMock(),
        # squeue runs every poll to measure reserved time (issue #47).
        "job_allocation": AsyncMock(return_value=JobAllocation()),
        "update_allocation": AsyncMock(),
        "accumulate_reserved": AsyncMock(),
    }
    with patch("clusterpilot.jobs.daemon.find_array_logs", new=mocks["find_array_logs"]), \
         patch("clusterpilot.jobs.daemon.job_efficiency", new=mocks["job_efficiency"]), \
         patch("clusterpilot.jobs.daemon.job_accounting", new=mocks["job_accounting"]), \
         patch("clusterpilot.jobs.daemon.update_accounting", new=mocks["update_accounting"]), \
         patch("clusterpilot.jobs.daemon.job_allocation", new=mocks["job_allocation"]), \
         patch("clusterpilot.jobs.daemon.update_allocation", new=mocks["update_allocation"]), \
         patch("clusterpilot.jobs.daemon.accumulate_reserved", new=mocks["accumulate_reserved"]), \
         patch("clusterpilot.jobs.daemon.query_status",
               new=AsyncMock(return_value=status)), \
         patch("clusterpilot.jobs.daemon.update_status", new=mocks["update_status"]), \
         patch("clusterpilot.jobs.daemon.record_download_attempt", new=AsyncMock()), \
         patch("clusterpilot.jobs.daemon.download", new=mocks["download"]), \
         patch("clusterpilot.jobs.daemon.notify_started", new=mocks["notify_started"]), \
         patch("clusterpilot.jobs.daemon.notify_completed", new=mocks["notify_completed"]), \
         patch("clusterpilot.jobs.daemon.notify_failed", new=mocks["notify_failed"]), \
         patch("clusterpilot.jobs.daemon.find_log", new=mocks["find_log"]), \
         patch("clusterpilot.jobs.daemon.tail_log", new=mocks["tail_log"]), \
         patch("clusterpilot.jobs.daemon.log_completed_job", new=mocks["log_completed_job"]), \
         patch.object(daemon, "_sync", new=AsyncMock()), \
         patch.object(daemon, "_sync_and_notify_completed", new=AsyncMock()) as completed:
        mocks["_sync_and_notify_completed"] = completed
        await daemon._poll_job(MagicMock(), _PROFILE, job)
    return mocks


def _written_statuses(update_status: AsyncMock) -> list[str]:
    return [call.args[3] for call in update_status.await_args_list]


class TestSqueueOutageOnMixedArray:
    """Issue #27: sacct's first line is task 0, which is usually COMPLETED."""

    async def test_does_not_run_the_completion_path(self):
        status = JobStatus(
            state="RUNNING",
            counts={"COMPLETED": 1, "RUNNING": 1, "PENDING": 8},
            source="sacct",
        )
        mocks = await _poll(_make_job(status="PENDING"), status)
        mocks["_sync_and_notify_completed"].assert_not_called()
        mocks["download"].assert_not_called()

    async def test_writes_the_aggregate_state_not_completed(self):
        status = JobStatus(
            state="PENDING",
            counts={"COMPLETED": 4, "PENDING": 6},
            source="sacct",
        )
        mocks = await _poll(_make_job(status="PENDING"), status)
        written = _written_statuses(mocks["update_status"])
        assert written
        assert "COMPLETED" not in written
        assert set(written) == {"PENDING"}

    async def test_records_the_task_breakdown(self):
        status = JobStatus(
            state="RUNNING",
            counts={"COMPLETED": 1, "RUNNING": 1, "PENDING": 8},
            source="sacct",
        )
        job = _make_job(status="PENDING")
        mocks = await _poll(job, status)
        assert job.status_detail == "1R/8PD/1C"
        details = [
            call.kwargs.get("status_detail")
            for call in mocks["update_status"].await_args_list
        ]
        assert "1R/8PD/1C" in details


class TestRunningTransition:
    async def test_notifies_on_first_start(self):
        status = JobStatus(state="RUNNING", counts={"RUNNING": 1}, source="squeue")
        mocks = await _poll(_make_job(status="PENDING"), status)
        mocks["notify_started"].assert_awaited_once()

    async def test_does_not_re_notify_when_already_started(self):
        # An array that dipped back to PENDING between waves is running again.
        status = JobStatus(
            state="RUNNING",
            counts={"RUNNING": 3, "PENDING": 5},
            source="squeue",
        )
        job = _make_job(status="PENDING", started_at=1000.0)
        mocks = await _poll(job, status)
        mocks["notify_started"].assert_not_called()
        mocks["find_log"].assert_not_called()
        assert job.started_at == 1000.0


class TestTerminalMixedArray:
    """Issue #1: a partly failed array must sync results and report failure."""

    async def test_downloads_once_and_notifies_failure(self):
        status = JobStatus(
            state="FAILED",
            counts={"COMPLETED": 31, "FAILED": 1},
            source="sacct",
        )
        mocks = await _poll(_make_job(status="RUNNING"), status)
        mocks["download"].assert_awaited_once()
        mocks["notify_failed"].assert_awaited_once()

    async def test_does_not_log_to_fieldnotes(self):
        status = JobStatus(
            state="FAILED",
            counts={"COMPLETED": 31, "FAILED": 1},
            source="sacct",
        )
        mocks = await _poll(_make_job(status="RUNNING"), status)
        mocks["log_completed_job"].assert_not_called()
        mocks["_sync_and_notify_completed"].assert_not_called()

    async def test_wholesale_failure_does_not_download(self):
        status = JobStatus(
            state="FAILED",
            counts={"FAILED": 32},
            source="sacct",
        )
        mocks = await _poll(_make_job(status="RUNNING"), status)
        mocks["download"].assert_not_called()
        mocks["notify_failed"].assert_awaited_once()


class TestArrayLogDiscovery:
    """Issue #2: array tasks write %x-%A-%a.out, which find_log never matched,
    so log_path stayed NULL for every array job."""

    _LOGS = {
        "0": "/home/juliaf/jobs/bench_run/bench_run-12345-0.out",
        "1": "/home/juliaf/jobs/bench_run/bench_run-12345-1.out",
        "2": "/home/juliaf/jobs/bench_run/bench_run-12345-2.out",
    }

    async def test_running_array_stores_the_lowest_tasks_log(self):
        status = JobStatus(state="RUNNING", counts={"RUNNING": 3}, source="squeue")
        job = _make_job(status="PENDING", array_spec="0-2")
        mocks = await _poll(job, status, array_logs=self._LOGS)
        mocks["find_array_logs"].assert_awaited()
        mocks["find_log"].assert_not_called()
        assert job.log_path == self._LOGS["0"]
        paths = [
            call.kwargs.get("log_path")
            for call in mocks["update_status"].await_args_list
        ]
        assert self._LOGS["0"] in paths

    async def test_a_non_array_job_still_uses_find_log(self):
        status = JobStatus(state="RUNNING", counts={"RUNNING": 1}, source="squeue")
        job = _make_job(status="PENDING")
        mocks = await _poll(job, status)
        mocks["find_log"].assert_awaited_once()
        assert job.log_path == "/home/juliaf/jobs/bench_run/out"

    async def test_an_array_with_no_task_logs_falls_back_to_find_log(self):
        status = JobStatus(state="RUNNING", counts={"RUNNING": 1}, source="squeue")
        job = _make_job(status="PENDING", array_spec="0-2")
        mocks = await _poll(job, status, array_logs={})
        mocks["find_log"].assert_awaited_once()
        assert job.log_path == "/home/juliaf/jobs/bench_run/out"

    async def test_failure_excerpt_skips_tasks_whose_log_is_empty(self):
        status = JobStatus(
            state="FAILED", counts={"COMPLETED": 2, "FAILED": 1}, source="sacct",
        )
        job = _make_job(status="RUNNING", array_spec="0-2")
        mocks = await _poll(
            job, status,
            array_logs=self._LOGS,
            tails={self._LOGS["1"]: "ERROR: out of memory"},
        )
        mocks["notify_failed"].assert_awaited_once()
        assert mocks["notify_failed"].await_args.args[2] == "ERROR: out of memory"

    async def test_failure_excerpt_tries_at_most_three_tasks(self):
        status = JobStatus(state="FAILED", counts={"FAILED": 9}, source="sacct")
        many = {str(i): f"/home/juliaf/jobs/bench_run/bench_run-12345-{i}.out"
                for i in range(9)}
        job = _make_job(status="RUNNING", array_spec="0-8")
        mocks = await _poll(job, status, array_logs=many, tails={})
        tried = [call.args[2] for call in mocks["tail_log"].await_args_list]
        assert [p for p in tried if p in many.values()] == [
            many["0"], many["1"], many["2"],
        ]


class TestEfficiencyAtTerminalTransition:
    """Issue #31: seff runs once, when the job leaves the queue."""

    async def test_stored_and_carried_into_the_completion_notification(self):
        status = JobStatus(state="COMPLETED", counts={"COMPLETED": 1}, source="sacct")
        job = _make_job(status="RUNNING", started_at=1.0)
        daemon = _make_daemon()

        mocks = {
            "update_status": AsyncMock(),
            "download": AsyncMock(),
            "notify_completed": AsyncMock(),
            "notify_failed": AsyncMock(),
            "find_array_logs": AsyncMock(return_value={}),
            "find_log": AsyncMock(return_value=None),
            "tail_log": AsyncMock(return_value=""),
            "log_completed_job": MagicMock(),
            "job_efficiency": AsyncMock(return_value="CPU 12%, mem 6% of 16 GB"),
            "job_accounting": AsyncMock(return_value=JobAccounting()),
            "update_accounting": AsyncMock(),
            "job_allocation": AsyncMock(return_value=JobAllocation()),
            "update_allocation": AsyncMock(),
            "accumulate_reserved": AsyncMock(),
        }
        with patch("clusterpilot.jobs.daemon.query_status",
                   new=AsyncMock(return_value=status)), \
             patch("clusterpilot.jobs.daemon.update_status", new=mocks["update_status"]), \
             patch("clusterpilot.jobs.daemon.record_download_attempt", new=AsyncMock()), \
             patch("clusterpilot.jobs.daemon.download", new=mocks["download"]), \
             patch("clusterpilot.jobs.daemon.notify_completed", new=mocks["notify_completed"]), \
             patch("clusterpilot.jobs.daemon.notify_failed", new=mocks["notify_failed"]), \
             patch("clusterpilot.jobs.daemon.find_array_logs", new=mocks["find_array_logs"]), \
             patch("clusterpilot.jobs.daemon.find_log", new=mocks["find_log"]), \
             patch("clusterpilot.jobs.daemon.tail_log", new=mocks["tail_log"]), \
             patch("clusterpilot.jobs.daemon.log_completed_job", new=mocks["log_completed_job"]), \
             patch("clusterpilot.jobs.daemon.job_efficiency", new=mocks["job_efficiency"]), \
             patch("clusterpilot.jobs.daemon.job_accounting", new=mocks["job_accounting"]), \
             patch("clusterpilot.jobs.daemon.update_accounting", new=mocks["update_accounting"]), \
             patch("clusterpilot.jobs.daemon.job_allocation", new=mocks["job_allocation"]), \
             patch("clusterpilot.jobs.daemon.update_allocation", new=mocks["update_allocation"]), \
             patch("clusterpilot.jobs.daemon.accumulate_reserved", new=mocks["accumulate_reserved"]), \
             patch.object(daemon, "_sync", new=AsyncMock()):
            await daemon._poll_job(MagicMock(), _PROFILE, job)

        mocks["job_efficiency"].assert_awaited_once()
        assert mocks["job_efficiency"].await_args.args[2] == "12345"
        written = [
            call.kwargs.get("efficiency")
            for call in mocks["update_status"].await_args_list
        ]
        assert "CPU 12%, mem 6% of 16 GB" in written
        # The notification is sent after the fetch, so it can carry the figure.
        assert job.efficiency == "CPU 12%, mem 6% of 16 GB"
        notified = mocks["notify_completed"].await_args.args[1]
        assert notified.efficiency == "CPU 12%, mem 6% of 16 GB"

    async def test_an_array_asks_seff_about_its_lowest_task(self):
        status = JobStatus(state="FAILED", counts={"FAILED": 10}, source="sacct")
        job = _make_job(status="RUNNING", started_at=1.0, array_spec="0-9")
        mocks = await _poll(
            job, status,
            array_logs={
                "3": "/home/juliaf/jobs/bench_run/bench_run-12345-3.out",
                "7": "/home/juliaf/jobs/bench_run/bench_run-12345-7.out",
            },
        )
        assert mocks["job_efficiency"].await_args.args[2] == "12345_3"

    async def test_an_empty_result_writes_nothing(self):
        status = JobStatus(state="FAILED", counts={"FAILED": 1}, source="sacct")
        mocks = await _poll(_make_job(status="RUNNING", started_at=1.0), status)
        assert all(
            call.kwargs.get("efficiency") is None
            for call in mocks["update_status"].await_args_list
        )


class TestAccountingAtTerminalTransition:
    """sacct is asked once, when the job finishes, and the answer is kept."""

    _ACCT = JobAccounting(
        cpus=4, gpus=1, nodes=1,
        runtime_seconds=3600, core_seconds=14400.0, gpu_seconds=3600.0,
        exit_code="0:0", tasks=1,
    )

    async def _poll_terminal(self, acct: JobAccounting, **job_kwargs):
        status = JobStatus(state="COMPLETED", counts={"COMPLETED": 1}, source="sacct")
        job = _make_job(status="RUNNING", started_at=1.0, **job_kwargs)
        daemon = _make_daemon()
        mocks = {
            "update_status": AsyncMock(),
            "update_accounting": AsyncMock(),
            "download": AsyncMock(),
            "notify_completed": AsyncMock(),
            "notify_failed": AsyncMock(),
            "find_array_logs": AsyncMock(return_value={}),
            "find_log": AsyncMock(return_value=None),
            "tail_log": AsyncMock(return_value=""),
            "log_completed_job": MagicMock(),
            "job_efficiency": AsyncMock(return_value=""),
            "job_accounting": AsyncMock(return_value=acct),
            "job_allocation": AsyncMock(return_value=JobAllocation()),
            "update_allocation": AsyncMock(),
            "accumulate_reserved": AsyncMock(),
        }
        with patch("clusterpilot.jobs.daemon.query_status",
                   new=AsyncMock(return_value=status)), \
             patch("clusterpilot.jobs.daemon.update_status", new=mocks["update_status"]), \
             patch("clusterpilot.jobs.daemon.record_download_attempt", new=AsyncMock()), \
             patch("clusterpilot.jobs.daemon.update_accounting", new=mocks["update_accounting"]), \
             patch("clusterpilot.jobs.daemon.job_allocation", new=mocks["job_allocation"]), \
             patch("clusterpilot.jobs.daemon.update_allocation", new=mocks["update_allocation"]), \
             patch("clusterpilot.jobs.daemon.accumulate_reserved", new=mocks["accumulate_reserved"]), \
             patch("clusterpilot.jobs.daemon.download", new=mocks["download"]), \
             patch("clusterpilot.jobs.daemon.notify_completed", new=mocks["notify_completed"]), \
             patch("clusterpilot.jobs.daemon.notify_failed", new=mocks["notify_failed"]), \
             patch("clusterpilot.jobs.daemon.find_array_logs", new=mocks["find_array_logs"]), \
             patch("clusterpilot.jobs.daemon.find_log", new=mocks["find_log"]), \
             patch("clusterpilot.jobs.daemon.tail_log", new=mocks["tail_log"]), \
             patch("clusterpilot.jobs.daemon.log_completed_job", new=mocks["log_completed_job"]), \
             patch("clusterpilot.jobs.daemon.job_efficiency", new=mocks["job_efficiency"]), \
             patch("clusterpilot.jobs.daemon.job_accounting", new=mocks["job_accounting"]), \
             patch.object(daemon, "_sync", new=AsyncMock()):
            await daemon._poll_job(MagicMock(), _PROFILE, job)
        return job, mocks

    async def test_asked_once_about_the_array_master(self):
        # sacct answers for every task from the master id, unlike seff.
        _, mocks = await self._poll_terminal(self._ACCT, array_spec="0-9")
        mocks["job_accounting"].assert_awaited_once()
        assert mocks["job_accounting"].await_args.args[2] == "12345"

    async def test_persisted(self):
        _, mocks = await self._poll_terminal(self._ACCT)
        mocks["update_accounting"].assert_awaited_once()
        assert mocks["update_accounting"].await_args.args[3] == self._ACCT

    async def test_set_on_the_record_before_the_sync_that_follows(self):
        job, _ = await self._poll_terminal(self._ACCT)
        assert job.alloc_cpus == 4
        assert job.alloc_gpus == 1
        assert job.core_seconds == 14400.0
        assert job.gpu_seconds == 3600.0
        assert job.runtime_seconds == 3600
        assert job.exit_code == "0:0"

    async def test_a_cluster_without_accounting_leaves_the_record_unknown(self):
        job, mocks = await self._poll_terminal(JobAccounting())
        assert job.alloc_cpus is None
        assert job.core_seconds is None
        assert job.exit_code == ""
        # Still called: the writer itself decides an empty record is a no-op.
        mocks["update_accounting"].assert_awaited_once()

    async def test_a_sacct_failure_does_not_stop_the_completion_path(self):
        status = JobStatus(state="COMPLETED", counts={"COMPLETED": 1}, source="sacct")
        job = _make_job(status="RUNNING", started_at=1.0)
        daemon = _make_daemon()
        completed = AsyncMock()
        with patch("clusterpilot.jobs.daemon.query_status",
                   new=AsyncMock(return_value=status)), \
             patch("clusterpilot.jobs.daemon.update_status", new=AsyncMock()), \
             patch("clusterpilot.jobs.daemon.record_download_attempt", new=AsyncMock()), \
             patch("clusterpilot.jobs.daemon.update_accounting", new=AsyncMock()), \
             patch("clusterpilot.jobs.daemon.job_allocation",
                   new=AsyncMock(return_value=JobAllocation())), \
             patch("clusterpilot.jobs.daemon.update_allocation", new=AsyncMock()), \
             patch("clusterpilot.jobs.daemon.accumulate_reserved", new=AsyncMock()), \
             patch("clusterpilot.jobs.daemon.job_efficiency", new=AsyncMock(return_value="")), \
             patch("clusterpilot.jobs.daemon.job_accounting",
                   new=AsyncMock(side_effect=RuntimeError("slurmdbd unreachable"))), \
             patch("clusterpilot.jobs.daemon.find_array_logs", new=AsyncMock(return_value={})), \
             patch.object(daemon, "_sync_and_notify_completed", new=completed):
            await daemon._poll_job(MagicMock(), _PROFILE, job)
        completed.assert_awaited_once()
        assert job.core_seconds is None

    async def test_an_empty_answer_does_not_blank_what_is_already_held(self):
        # Belt and braces: the writer skips an empty record, so the in-memory
        # record must not be cleared either.
        job, _ = await self._poll_terminal(
            JobAccounting(),
            alloc_cpus=8, core_seconds=999.0, exit_code="1:0",
        )
        assert job.alloc_cpus == 8
        assert job.core_seconds == 999.0
        assert job.exit_code == "1:0"
