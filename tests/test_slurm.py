"""Tests for cluster/slurm.py — submit, status polling, log helpers."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from clusterpilot.cluster.slurm import (
    TERMINAL_STATES,
    JobStatus,
    SlurmError,
    JobAccounting,
    _parse_accounting,
    _parse_accounting_by_job,
    _parse_efficiency,
    _parse_tres,
    _worst_exit_code,
    aggregate,
    find_array_logs,
    find_log,
    job_accounting,
    job_accounting_many,
    job_efficiency,
    job_status,
    query_status,
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


# ── aggregate ─────────────────────────────────────────────────────────────────

class TestAggregate:
    def test_single_state_passes_through(self):
        assert aggregate(["RUNNING"]) == "RUNNING"

    def test_unusual_single_state_passes_through(self):
        assert aggregate(["SUSPENDED", "SUSPENDED"]) == "SUSPENDED"

    def test_running_beats_pending(self):
        assert aggregate(["RUNNING", "PENDING"]) == "RUNNING"

    def test_completing_counts_as_running(self):
        assert aggregate(["COMPLETING", "PENDING"]) == "RUNNING"

    def test_completed_plus_pending_is_pending(self):
        # Issue #27: an array with tasks still queued is not finished.
        assert aggregate(["COMPLETED", "PENDING"]) == "PENDING"

    def test_completed_plus_failed_is_failed(self):
        # Issue #1: a partly failed array must not report COMPLETED.
        assert aggregate(["COMPLETED", "FAILED"]) == "FAILED"

    def test_all_completed_is_completed(self):
        assert aggregate(["COMPLETED", "COMPLETED", "COMPLETED"]) == "COMPLETED"

    def test_cancelled_by_suffix_normalised(self):
        assert aggregate(["CANCELLED by 12345", "COMPLETED"]) == "CANCELLED"

    def test_plus_suffix_normalised(self):
        assert aggregate(["COMPLETED+", "COMPLETED"]) == "COMPLETED"

    def test_failed_outranks_timeout(self):
        assert aggregate(["TIMEOUT", "FAILED"]) == "FAILED"

    def test_timeout_outranks_cancelled(self):
        assert aggregate(["CANCELLED", "TIMEOUT"]) == "TIMEOUT"

    def test_empty_input_returns_empty_string(self):
        assert aggregate([]) == ""


# ── JobStatus.summary ─────────────────────────────────────────────────────────

class TestJobStatusSummary:
    def test_empty_for_single_record(self):
        js = JobStatus(state="RUNNING", counts={"RUNNING": 1}, source="squeue")
        assert js.summary == ""

    def test_running_before_pending(self):
        js = JobStatus(
            state="RUNNING",
            counts={"PENDING": 27, "RUNNING": 5},
            source="squeue",
        )
        assert js.summary == "5R/27PD"

    def test_terminal_states_ordered_completed_first(self):
        js = JobStatus(
            state="FAILED",
            counts={"FAILED": 1, "COMPLETED": 31},
            source="sacct",
        )
        assert js.summary == "31C/1F"

    def test_unknown_state_uses_full_name(self):
        js = JobStatus(
            state="SUSPENDED",
            counts={"SUSPENDED": 2, "RUNNING": 1},
            source="squeue",
        )
        assert js.summary == "1R/2SUSPENDED"


# ── query_status parsing ──────────────────────────────────────────────────────

class TestQueryStatusParsing:
    async def test_bracket_range_counts_every_task(self):
        with patch(
            "clusterpilot.cluster.slurm.run_remote",
            _mock_run_remote("123_[5-31]|PENDING"),
        ):
            js = await query_status("host", "user", "123")
        assert js is not None
        assert js.counts == {"PENDING": 27}

    async def test_mixed_range_and_singletons(self):
        with patch(
            "clusterpilot.cluster.slurm.run_remote",
            _mock_run_remote("123_[0-3,7]|PENDING"),
        ):
            js = await query_status("host", "user", "123")
        assert js.counts == {"PENDING": 5}

    async def test_throttle_suffix_stripped(self):
        with patch(
            "clusterpilot.cluster.slurm.run_remote",
            _mock_run_remote("123_[5-31%5]|PENDING"),
        ):
            js = await query_status("host", "user", "123")
        assert js.counts == {"PENDING": 27}

    async def test_bare_state_line_still_parses(self):
        with patch(
            "clusterpilot.cluster.slurm.run_remote",
            _mock_run_remote("RUNNING"),
        ):
            js = await query_status("host", "user", "123")
        assert js.state == "RUNNING"
        assert js.counts == {"RUNNING": 1}

    async def test_trailing_separator_ignored(self):
        with patch(
            "clusterpilot.cluster.slurm.run_remote",
            _mock_run_remote("123_0|COMPLETED|\n123_1|COMPLETED|"),
        ):
            js = await query_status("host", "user", "123")
        assert js.counts == {"COMPLETED": 2}

    async def test_plain_job_id_counts_one(self):
        with patch(
            "clusterpilot.cluster.slurm.run_remote",
            _mock_run_remote("123|RUNNING"),
        ):
            js = await query_status("host", "user", "123")
        assert js.counts == {"RUNNING": 1}


# ── query_status aggregation ──────────────────────────────────────────────────

class TestQueryStatus:
    async def test_squeue_multiline_array_is_running(self):
        # Issue #1: mixed array must aggregate, not return "RUNNING\nPENDING".
        out = "77_1|RUNNING\n77_[2-28]|PENDING"
        with patch("clusterpilot.cluster.slurm.run_remote", _mock_run_remote(out)):
            js = await query_status("host", "user", "77")
        assert js.state == "RUNNING"
        assert js.source == "squeue"
        assert js.counts == {"RUNNING": 1, "PENDING": 27}
        assert js.summary == "1R/27PD"

    async def test_squeue_outage_does_not_declare_array_complete(self):
        # Issue #27 regression: squeue times out, sacct's first line is task 0
        # (COMPLETED), but tasks are still running and queued.
        mock = AsyncMock(side_effect=[
            SSHError("slurm_load_jobs error: Socket timed out"),
            "123_0|COMPLETED\n123_1|RUNNING\n123_[2-9]|PENDING",
        ])
        with patch("clusterpilot.cluster.slurm.run_remote", mock):
            js = await query_status("host", "user", "123")
        assert js.state == "RUNNING"
        assert js.source == "sacct"
        assert js.summary == "1R/8PD/1C"

    async def test_job_status_wrapper_agrees_on_the_27_case(self):
        mock = AsyncMock(side_effect=[
            SSHError("slurm_load_jobs error: Socket timed out"),
            "123_0|COMPLETED\n123_1|RUNNING\n123_[2-9]|PENDING",
        ])
        with patch("clusterpilot.cluster.slurm.run_remote", mock):
            state = await job_status("host", "user", "123")
        assert state == "RUNNING"

    async def test_returns_none_when_both_commands_fail(self):
        mock = AsyncMock(side_effect=SSHError("no connection"))
        with patch("clusterpilot.cluster.slurm.run_remote", mock):
            assert await query_status("host", "user", "99999") is None


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


# ── find_array_logs ─────────────────────────────────────────────────────────────

class TestFindArrayLogs:
    async def test_maps_task_index_to_path_in_numeric_order(self):
        # ls returns lexical order (10 before 2); we expect numeric ordering.
        listing = (
            "/home/user/myjob/myjob-99-0.out\n"
            "/home/user/myjob/myjob-99-1.out\n"
            "/home/user/myjob/myjob-99-10.out\n"
            "/home/user/myjob/myjob-99-2.out\n"
        )
        with patch("clusterpilot.cluster.slurm.run_remote", _mock_run_remote(listing)):
            tasks = await find_array_logs(
                "host", "user", "myjob", "99", "/home/user/myjob",
            )
        assert list(tasks.keys()) == ["0", "1", "2", "10"]
        assert tasks["2"] == "/home/user/myjob/myjob-99-2.out"

    async def test_lowest_task_is_first(self):
        listing = (
            "/home/user/myjob/myjob-99-3.out\n"
            "/home/user/myjob/myjob-99-0.out\n"
        )
        with patch("clusterpilot.cluster.slurm.run_remote", _mock_run_remote(listing)):
            tasks = await find_array_logs(
                "host", "user", "myjob", "99", "/home/user/myjob",
            )
        assert next(iter(tasks)) == "0"

    async def test_empty_when_no_task_logs(self):
        with patch("clusterpilot.cluster.slurm.run_remote", _mock_run_remote("")):
            tasks = await find_array_logs(
                "host", "user", "myjob", "99", "/home/user/myjob",
            )
        assert tasks == {}

    async def test_empty_on_ssh_error(self):
        with patch(
            "clusterpilot.cluster.slurm.run_remote",
            _mock_run_remote_raises(SSHError("gone")),
        ):
            tasks = await find_array_logs(
                "host", "user", "myjob", "99", "/home/user/myjob",
            )
        assert tasks == {}

    async def test_ignores_non_matching_lines(self):
        # The non-array single-file log and an unrelated file must not match.
        listing = (
            "/home/user/myjob/myjob-99.out\n"        # no task suffix
            "/home/user/myjob/myjob-99-0.out\n"      # task 0
            "/home/user/myjob/results.txt\n"         # unrelated
        )
        with patch("clusterpilot.cluster.slurm.run_remote", _mock_run_remote(listing)):
            tasks = await find_array_logs(
                "host", "user", "myjob", "99", "/home/user/myjob",
            )
        assert tasks == {"0": "/home/user/myjob/myjob-99-0.out"}

    async def test_globs_against_job_name_and_id(self):
        mock = _mock_run_remote("/home/user/myjob/myjob-99-0.out")
        with patch("clusterpilot.cluster.slurm.run_remote", mock):
            await find_array_logs("host", "user", "myjob", "99", "/home/user/myjob")
        cmd = mock.call_args[0][2]
        assert "/home/user/myjob/myjob-99-*.out" in cmd


# ── seff: job efficiency (issue #31) ──────────────────────────────────────────

_SEFF_OUTPUT = """Job ID: 8271604
Cluster: narval
User/Group: juliaf/juliaf
State: COMPLETED (exit code 0)
Cores: 1
CPU Utilized: 00:10:15
CPU Efficiency: 12.34% of 01:23:45 core-walltime
Job Wall-clock time: 01:23:45
Memory Utilized: 918.40 MB
Memory Efficiency: 5.60% of 16.00 GB
"""


class TestParseEfficiency:
    def test_real_shaped_output(self):
        assert _parse_efficiency(_SEFF_OUTPUT) == "CPU 12%, mem 6% of 16 GB"

    def test_percentages_round_to_integers(self):
        output = (
            "CPU Efficiency: 99.60% of 10:00:00 core-walltime\n"
            "Memory Efficiency: 49.50% of 8.00 GB\n"
        )
        assert _parse_efficiency(output) == "CPU 100%, mem 50% of 8 GB"

    def test_a_missing_memory_line_drops_that_half(self):
        output = "CPU Efficiency: 12.34% of 01:23:45 core-walltime\n"
        assert _parse_efficiency(output) == "CPU 12%"

    def test_a_missing_cpu_line_drops_that_half(self):
        output = "Memory Efficiency: 5.60% of 16.00 GB\n"
        assert _parse_efficiency(output) == "mem 6% of 16 GB"

    def test_the_reported_unit_is_kept(self):
        output = "Memory Efficiency: 10.00% of 512.00 MB\n"
        assert _parse_efficiency(output) == "mem 10% of 512 MB"

    def test_nothing_useful_gives_an_empty_string(self):
        assert _parse_efficiency("") == ""
        assert _parse_efficiency("seff: command not found") == ""


class TestJobEfficiency:
    async def test_runs_seff_for_the_job(self):
        with patch("clusterpilot.cluster.slurm.run_remote",
                   new=AsyncMock(return_value=_SEFF_OUTPUT)) as run:
            result = await job_efficiency("yak", "juliaf", "8271604")
        assert result == "CPU 12%, mem 6% of 16 GB"
        assert "seff 8271604" in run.await_args.args[2]

    async def test_an_array_task_id_is_passed_through(self):
        with patch("clusterpilot.cluster.slurm.run_remote",
                   new=AsyncMock(return_value=_SEFF_OUTPUT)) as run:
            await job_efficiency("yak", "juliaf", "8271604_3")
        assert "seff 8271604_3" in run.await_args.args[2]

    async def test_an_ssh_failure_is_swallowed(self):
        with patch("clusterpilot.cluster.slurm.run_remote",
                   new=AsyncMock(side_effect=SSHError("no socket"))):
            assert await job_efficiency("yak", "juliaf", "1") == ""

    async def test_any_other_failure_is_swallowed(self):
        with patch("clusterpilot.cluster.slurm.run_remote",
                   new=AsyncMock(side_effect=RuntimeError("boom"))):
            assert await job_efficiency("yak", "juliaf", "1") == ""


# ── Accounting (sacct) ────────────────────────────────────────────────────────

# One finished single-task job: 4 CPUs, 1 GPU, 1 node, 3600 s, exited cleanly.
_SACCT_SINGLE = "8271604|billing=4,cpu=4,gres/gpu=1,mem=16G,node=1|3600|0:0\n"

# A three-task array where every task ran for a different length of time, and
# the middle one was killed by the out-of-memory killer.
_SACCT_ARRAY = (
    "8271604_0|billing=2,cpu=2,mem=8G,node=1|100|0:0\n"
    "8271604_1|billing=2,cpu=2,mem=8G,node=1|200|0:9\n"
    "8271604_2|billing=2,cpu=2,mem=8G,node=1|300|1:0\n"
)


class TestParseTres:
    def test_reads_the_resources_it_is_asked_about(self):
        parsed = _parse_tres("billing=4,cpu=4,gres/gpu=1,mem=16G,node=1")
        assert parsed["cpu"] == 4
        assert parsed["gres/gpu"] == 1
        assert parsed["node"] == 1

    def test_a_unit_suffix_does_not_stop_the_numeric_prefix_being_read(self):
        assert _parse_tres("mem=16G")["mem"] == 16

    def test_an_entry_without_an_equals_sign_is_skipped(self):
        assert _parse_tres("cpu=4,nonsense,node=1") == {"cpu": 4.0, "node": 1.0}

    def test_an_empty_string_yields_nothing(self):
        assert _parse_tres("") == {}


class TestWorstExitCode:
    def test_a_signal_outranks_a_clean_exit(self):
        assert _worst_exit_code(["0:0", "0:9"]) == "0:9"

    def test_a_non_zero_exit_beats_a_clean_one(self):
        assert _worst_exit_code(["0:0", "1:0"]) == "1:0"

    def test_a_signal_outranks_an_exit_code(self):
        assert _worst_exit_code(["137:0", "0:9"]) == "0:9"

    def test_a_single_clean_code_is_still_reported(self):
        assert _worst_exit_code(["0:0"]) == "0:0"

    def test_unparseable_codes_are_skipped(self):
        assert _worst_exit_code(["nonsense", "1:0"]) == "1:0"

    def test_nothing_at_all_gives_an_empty_string(self):
        assert _worst_exit_code([]) == ""


class TestParseAccounting:
    def test_a_single_task_job(self):
        acct = _parse_accounting(_SACCT_SINGLE)
        assert acct.cpus == 4
        assert acct.gpus == 1
        assert acct.nodes == 1
        assert acct.runtime_seconds == 3600
        assert acct.core_seconds == 4 * 3600
        assert acct.gpu_seconds == 1 * 3600
        assert acct.exit_code == "0:0"
        assert acct.tasks == 1

    def test_an_array_sums_reserved_time_over_every_task(self):
        acct = _parse_accounting(_SACCT_ARRAY)
        assert acct.tasks == 3
        # Per-task allocation, not the array total.
        assert acct.cpus == 2
        # Wall duration is the longest task, not the sum.
        assert acct.runtime_seconds == 300
        # Reserved CPU time is the sum: 2 x (100 + 200 + 300).
        assert acct.core_seconds == 1200

    def test_an_array_reports_the_worst_task_exit_code(self):
        assert _parse_accounting(_SACCT_ARRAY).exit_code == "0:9"

    def test_a_job_with_no_gpu_reports_none_rather_than_zero(self):
        acct = _parse_accounting(_SACCT_ARRAY)
        assert acct.gpus is None
        assert acct.gpu_seconds is None

    def test_a_typed_gres_key_is_counted(self):
        acct = _parse_accounting("1|cpu=8,gres/gpu:a100=2,node=1|60|0:0\n")
        assert acct.gpus == 2
        assert acct.gpu_seconds == 120

    def test_the_plain_gres_key_wins_over_the_typed_one(self):
        # sacct prints both forms on some sites; summing them double-counts.
        acct = _parse_accounting("1|cpu=8,gres/gpu=2,gres/gpu:a100=2|60|0:0\n")
        assert acct.gpus == 2

    def test_a_task_with_no_allocation_does_not_lose_the_others(self):
        # sacct leaves AllocTRES empty for a task that never started.
        acct = _parse_accounting(
            "1_0||0|0:0\n"
            "1_1|cpu=4,node=1|100|0:0\n"
        )
        assert acct.tasks == 2
        assert acct.cpus == 4
        assert acct.core_seconds == 400

    def test_a_job_that_never_ran_reports_no_core_time(self):
        acct = _parse_accounting("1||0|0:0\n")
        assert acct.core_seconds is None
        assert acct.runtime_seconds == 0

    def test_malformed_lines_are_skipped(self):
        acct = _parse_accounting(
            "not a record\n"
            "1|cpu=4|notanumber|0:0\n"
            "2|cpu=4,node=1|50|0:0\n"
        )
        assert acct.tasks == 1
        assert acct.core_seconds == 200

    def test_empty_output_is_empty(self):
        acct = _parse_accounting("")
        assert acct.is_empty
        assert acct == JobAccounting()


class TestJobAccounting:
    async def test_asks_sacct_about_the_array_master(self):
        with patch("clusterpilot.cluster.slurm.run_remote",
                   new=AsyncMock(return_value=_SACCT_SINGLE)) as run:
            acct = await job_accounting("yak", "juliaf", "8271604")
        assert acct.cpus == 4
        cmd = run.await_args.args[2]
        assert "sacct -j 8271604" in cmd
        assert "AllocTRES" in cmd and "ElapsedRaw" in cmd and "ExitCode" in cmd
        # -X keeps it to the summary record, without the per-step rows.
        assert " -X " in cmd

    async def test_an_ssh_failure_is_swallowed(self):
        with patch("clusterpilot.cluster.slurm.run_remote",
                   new=AsyncMock(side_effect=SSHError("no socket"))):
            assert (await job_accounting("yak", "juliaf", "1")).is_empty

    async def test_any_other_failure_is_swallowed(self):
        with patch("clusterpilot.cluster.slurm.run_remote",
                   new=AsyncMock(side_effect=RuntimeError("boom"))):
            assert (await job_accounting("yak", "juliaf", "1")).is_empty


class TestParseAccountingByJob:
    def test_splits_one_sacct_output_into_one_record_per_job(self):
        by_job = _parse_accounting_by_job(
            "111|cpu=4,node=1|100|0:0\n"
            "222|cpu=8,node=2|200|1:0\n"
        )
        assert set(by_job) == {"111", "222"}
        assert by_job["111"].core_seconds == 400
        assert by_job["222"].core_seconds == 1600
        assert by_job["222"].exit_code == "1:0"

    def test_array_tasks_group_under_their_master(self):
        by_job = _parse_accounting_by_job(
            "333_0|cpu=2,node=1|100|0:0\n"
            "333_1|cpu=2,node=1|200|0:0\n"
            "444|cpu=1,node=1|50|0:0\n"
        )
        assert set(by_job) == {"333", "444"}
        assert by_job["333"].tasks == 2
        assert by_job["333"].core_seconds == 600
        assert by_job["333"].runtime_seconds == 200

    def test_a_job_sacct_does_not_know_is_simply_absent(self):
        assert "999" not in _parse_accounting_by_job("111|cpu=4|100|0:0\n")

    def test_empty_output_gives_nothing(self):
        assert _parse_accounting_by_job("") == {}


class TestJobAccountingMany:
    async def test_asks_about_every_job_in_one_call(self):
        run = AsyncMock(return_value="111|cpu=4,node=1|100|0:0\n222|cpu=8|200|0:0\n")
        with patch("clusterpilot.cluster.slurm.run_remote", new=run):
            found = await job_accounting_many("yak", "juliaf", ["111", "222"])
        assert run.await_count == 1
        assert "sacct -j 111,222" in run.await_args.args[2]
        assert set(found) == {"111", "222"}

    async def test_a_long_list_is_split_into_chunks(self):
        ids = [str(n) for n in range(120)]
        run = AsyncMock(return_value="")
        with patch("clusterpilot.cluster.slurm.run_remote", new=run):
            await job_accounting_many("yak", "juliaf", ids)
        assert run.await_count == 3, "50 per call"

    async def test_one_failed_chunk_does_not_lose_the_others(self):
        ids = [str(n) for n in range(60)]

        async def _flaky(host, user, cmd):
            if cmd.startswith("sacct -j 0,"):
                raise SSHError("dropped")
            return "50|cpu=4|100|0:0\n"

        with patch("clusterpilot.cluster.slurm.run_remote", new=AsyncMock(side_effect=_flaky)):
            found = await job_accounting_many("yak", "juliaf", ids)
        assert set(found) == {"50"}

    async def test_no_job_ids_makes_no_call(self):
        run = AsyncMock(return_value="")
        with patch("clusterpilot.cluster.slurm.run_remote", new=run):
            assert await job_accounting_many("yak", "juliaf", []) == {}
        run.assert_not_awaited()
