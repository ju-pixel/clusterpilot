"""The daemon's completion path logs to Fieldnotes only after a good download.

Exercises PollDaemon._sync_and_notify_completed in isolation: its remote calls
(download, update_status, notify, tail, hosted sync) are stubbed so the test
pins one contract — log_completed_job runs when the results download succeeds,
and is skipped when it raises.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from clusterpilot.config import ClusterProfile, Config, Defaults
from clusterpilot.db import JobRecord
from clusterpilot.jobs.daemon import PollDaemon
from clusterpilot.ssh.rsync import RsyncError


def _make_job() -> JobRecord:
    return JobRecord(
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


def _make_daemon() -> PollDaemon:
    return PollDaemon(Config(defaults=Defaults()), db_path=":memory:")


_PROFILE = ClusterProfile(name="grex", host="yak.hpc.umanitoba.ca", user="juliaf",
                          account="def-stamps", scratch="$HOME/jobs")


async def _run_completion(download_side_effect=None):
    daemon = _make_daemon()
    db = MagicMock()
    with patch("clusterpilot.jobs.daemon.download",
               new=AsyncMock(side_effect=download_side_effect)), \
         patch("clusterpilot.jobs.daemon.update_status", new=AsyncMock()), \
         patch("clusterpilot.jobs.daemon.notify_completed", new=AsyncMock()), \
         patch("clusterpilot.jobs.daemon.tail_log", new=AsyncMock(return_value="")), \
         patch.object(daemon, "_sync", new=AsyncMock()), \
         patch("clusterpilot.jobs.daemon.log_completed_job") as helper:
        await daemon._sync_and_notify_completed(db, _PROFILE, _make_job(), "COMPLETED")
    return helper


class TestDaemonFieldnotesCall:
    async def test_helper_called_on_successful_download(self):
        helper = await _run_completion(download_side_effect=None)
        helper.assert_called_once()

    async def test_helper_not_called_when_download_fails(self):
        helper = await _run_completion(download_side_effect=RsyncError("boom"))
        helper.assert_not_called()
