"""Which array task's log F1 shows, and which key cycles which group (#73).

A 54-task array on Rorqual had three tasks running and fifty-one finished.
TAIL cycled every task that had ever written a log, so it kept landing on
tasks that finished hours ago and the live output was several presses away.
The two questions an array is actually asked are "what is happening" and
"what went wrong", so TAIL now cycles the running tasks and LOG the
finished ones.

``JobsView`` is exercised as a bare widget: the resolver is deliberately
free of widgets and notifications, which is what makes that possible. The
two SSH calls behind it are stubbed.
"""
from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.widgets import RichLog

from clusterpilot.config import ClusterProfile, Config, Defaults
from clusterpilot.db import JobRecord
from clusterpilot.tui.app import ClusterPilotApp
from clusterpilot.tui.jobs import ArrayLogChoice, JobsView


def a_job(job_id: str = "4123456", array_spec: str = "0-53") -> JobRecord:
    return JobRecord(
        job_id=job_id,
        job_name="zfc-field-sweep",
        cluster_name="rorqual",
        host="rorqual.alliancecan.ca",
        user="jfrank",
        account="def-stamps",
        partition="",
        script_path="/scratch/jfrank/job/zfc.sh",
        working_dir="/scratch/jfrank/job",
        local_dir="/home/julia/clusterpilot_jobs/zfc",
        walltime="24:00:00",
        status="RUNNING",
        array_spec=array_spec,
    )


def a_view() -> JobsView:
    """A JobsView with the array state on_mount would have set.

    Constructed rather than mounted: everything under test here is decided
    before any widget is touched.
    """
    view = JobsView()
    view._array_job_id = None
    view._array_tasks = {}
    view._array_states = {}
    view._array_fetched_at = 0.0
    view._array_pos = {}
    return view


def logs_for(*tasks: str) -> dict[str, str]:
    return {task: f"/scratch/jfrank/job/zfc-4123456-{task}.out" for task in tasks}


def stub_cluster(tasks: dict[str, str], states: dict[str, str]):
    """Patch the two remote calls the resolver makes."""
    return (
        patch(
            "clusterpilot.tui.jobs.find_array_logs",
            new=AsyncMock(return_value=tasks),
        ),
        patch(
            "clusterpilot.tui.jobs.array_task_states",
            new=AsyncMock(return_value=states),
        ),
    )


async def resolve(view: JobsView, want: str, tasks, states) -> ArrayLogChoice:
    logs_patch, states_patch = stub_cluster(tasks, states)
    with logs_patch, states_patch:
        return await view._resolve_array_log(
            a_job(), "rorqual.alliancecan.ca", "jfrank", want=want,
        )


class TestTailCyclesTheRunningTasks:
    @pytest.mark.asyncio
    async def test_it_picks_a_task_that_is_running_now(self):
        tasks = logs_for("0", "1", "2", "50", "51", "52")
        states = {"50": "RUNNING", "51": "RUNNING", "52": "COMPLETING"}
        choice = await resolve(a_view(), "running", tasks, states)
        assert choice.task == "50"
        assert choice.matched == 3          # COMPLETING is still on a node
        assert choice.log_path.endswith("-50.out")

    @pytest.mark.asyncio
    async def test_repeat_presses_cycle_and_wrap(self):
        tasks = logs_for("0", "50", "51")
        states = {"50": "RUNNING", "51": "RUNNING"}
        view = a_view()
        seen = [
            (await resolve(view, "running", tasks, states)).task
            for _ in range(3)
        ]
        assert seen == ["50", "51", "50"]

    @pytest.mark.asyncio
    async def test_a_pending_task_is_not_running(self):
        tasks = logs_for("7")
        choice = await resolve(a_view(), "running", tasks, {"7": "PENDING"})
        assert choice.log_path == ""
        assert choice.total == 1

    @pytest.mark.asyncio
    async def test_nothing_running_says_so_rather_than_showing_another_task(self):
        tasks = logs_for("0", "1", "2")
        choice = await resolve(a_view(), "running", tasks, {})
        assert choice.log_path == ""
        assert choice.task == ""
        assert JobsView._no_array_task_message(choice).startswith(
            "[#7a6a50]No task of this array is running now."
        )


class TestLogCyclesTheFinishedTasks:
    @pytest.mark.asyncio
    async def test_a_task_absent_from_the_queue_has_finished(self):
        tasks = logs_for("0", "1", "50")
        states = {"50": "RUNNING"}
        choice = await resolve(a_view(), "finished", tasks, states)
        assert choice.task == "0"
        assert choice.matched == 2

    @pytest.mark.asyncio
    async def test_its_cursor_is_independent_of_tail(self):
        """Pressing T then L then T again returns to the running task the
        user was on, rather than being dragged along by the other cycle.
        """
        tasks = logs_for("0", "1", "50", "51")
        states = {"50": "RUNNING", "51": "RUNNING"}
        view = a_view()
        assert (await resolve(view, "running", tasks, states)).task == "50"
        assert (await resolve(view, "finished", tasks, states)).task == "0"
        assert (await resolve(view, "running", tasks, states)).task == "51"
        assert (await resolve(view, "finished", tasks, states)).task == "1"

    @pytest.mark.asyncio
    async def test_nothing_finished_says_so(self):
        tasks = logs_for("50")
        choice = await resolve(a_view(), "finished", tasks, {"50": "RUNNING"})
        assert choice.log_path == ""
        assert JobsView._no_array_task_message(choice).startswith(
            "[#7a6a50]No task of this array has finished yet."
        )


class TestNoLogsYet:
    @pytest.mark.asyncio
    async def test_an_array_before_its_first_log_says_so(self):
        choice = await resolve(a_view(), "running", {}, {})
        assert choice.log_path == ""
        assert choice.total == 0
        assert JobsView._no_array_task_message(choice) == (
            "[#7a6a50]Array task logs not found yet.[/]"
        )

    @pytest.mark.asyncio
    async def test_pending_tasks_count_towards_the_total(self):
        """The total is what the array has, not what has written a log: a
        header saying "running 2 of 2" on a 54-task array would be a lie.
        """
        tasks = logs_for("0", "1")
        states = {"2": "PENDING", "3": "PENDING"}
        choice = await resolve(a_view(), "finished", tasks, states)
        assert choice.total == 4


class TestSnapshotFreshness:
    @pytest.mark.asyncio
    async def test_a_task_that_starts_later_is_discovered(self):
        """The old code discovered the tasks once and never again while the
        job stayed selected, so a task that started after the first TAIL was
        invisible until the user clicked away and back.
        """
        view = a_view()
        first = await resolve(view, "running", logs_for("50"), {"50": "RUNNING"})
        assert first.task == "50"

        view._array_fetched_at -= 31   # the TTL has passed
        second = await resolve(
            view, "running", logs_for("50", "51"), {"51": "RUNNING"},
        )
        assert second.task == "51"

    @pytest.mark.asyncio
    async def test_a_press_inside_the_window_does_not_ask_the_cluster_again(self):
        view = a_view()
        tasks, states = logs_for("50", "51"), {"50": "RUNNING", "51": "RUNNING"}
        logs_patch, states_patch = stub_cluster(tasks, states)
        with logs_patch as find_logs, states_patch as fetch_states:
            job = a_job()
            for _ in range(3):
                await view._resolve_array_log(
                    job, "rorqual.alliancecan.ca", "jfrank", want="running",
                )
            assert find_logs.await_count == 1
            assert fetch_states.await_count == 1

    @pytest.mark.asyncio
    async def test_another_job_always_refetches_and_starts_over(self):
        view = a_view()
        tasks, states = logs_for("50", "51"), {"50": "RUNNING", "51": "RUNNING"}
        assert (await resolve(view, "running", tasks, states)).task == "50"
        assert (await resolve(view, "running", tasks, states)).task == "51"

        logs_patch, states_patch = stub_cluster(tasks, states)
        with logs_patch, states_patch:
            other = await view._resolve_array_log(
                a_job(job_id="4200000"), "rorqual.alliancecan.ca", "jfrank",
                want="running",
            )
        assert other.task == "50"


class TestLogHeader:
    def test_an_array_header_names_the_group_and_both_keys(self):
        header = JobsView._log_header(
            a_view(),
            "/scratch/jfrank/job/zfc-4123456-7.out",
            "last 500 lines",
            ArrayLogChoice(
                want="running",
                log_path="/scratch/jfrank/job/zfc-4123456-7.out",
                task="7",
                matched=3,
                total=54,
            ),
        )
        assert "array task 7" in header
        assert "running 3 of 54" in header
        assert r"\[T] cycles running" in header
        assert r"\[L] cycles finished" in header

    def test_a_plain_job_header_is_unchanged(self):
        header = JobsView._log_header(
            a_view(), "/scratch/jfrank/job/zfc-4123456.out", "last 500 lines",
        )
        assert header == "/scratch/jfrank/job/zfc-4123456.out (last 500 lines)"


# ── the two keys, on a running app ───────────────────────────────────────────

class TestTheKeysInTheApp:
    """The wiring: T asks for the running group, L for the finished one, and
    a plain job still tails its single log.
    """

    @staticmethod
    def _config() -> Config:
        return Config(
            defaults=Defaults(api_key="test-key"),
            clusters=[
                ClusterProfile(
                    name="rorqual",
                    host="rorqual.alliancecan.ca",
                    user="jfrank",
                    account="def-stamps",
                    scratch="$SCRATCH",
                    cluster_type="drac",
                )
            ],
        )

    @contextlib.contextmanager
    def _app_offline(self, tasks: dict[str, str], states: dict[str, str]):
        daemon = MagicMock()
        daemon.run_forever = AsyncMock()
        with patch("clusterpilot.tui.app.PollDaemon", return_value=daemon), \
                patch("clusterpilot.tui.app.is_connected", return_value=True), \
                patch("clusterpilot.tui.jobs.is_connected", return_value=True), \
                patch("clusterpilot.update.check_for_update", new=AsyncMock(return_value=None)), \
                patch(
                    "clusterpilot.tui.jobs.find_array_logs",
                    new=AsyncMock(return_value=tasks),
                ), \
                patch(
                    "clusterpilot.tui.jobs.array_task_states",
                    new=AsyncMock(return_value=states),
                ), \
                patch(
                    "clusterpilot.tui.jobs.find_log",
                    new=AsyncMock(return_value="/scratch/jfrank/job/zfc-4123456.out"),
                ), \
                patch(
                    "clusterpilot.tui.jobs.tail_log",
                    new=AsyncMock(return_value="line one\nline two\n"),
                ), \
                patch(
                    "clusterpilot.tui.jobs.cat_log",
                    new=AsyncMock(return_value="line one\nline two\n"),
                ):
            yield

    @staticmethod
    def _pane_text(app) -> str:
        pane = app.query_one("#log-display", RichLog)
        return "\n".join(str(strip) for line in pane.lines for strip in [line.text])

    @pytest.mark.asyncio
    async def test_tail_on_an_array_with_nothing_running_says_so(self, tmp_path):
        app = ClusterPilotApp(self._config(), db_path=tmp_path / "jobs.db")
        with self._app_offline(logs_for("0", "1"), {}):
            async with app.run_test(size=(100, 30)) as pilot:
                view = app.query_one(JobsView)
                await view._do_tail(a_job()).wait()
                await pilot.pause()
                assert "No task of this array is running now" in self._pane_text(app)

    @pytest.mark.asyncio
    async def test_log_on_an_array_shows_a_finished_task(self, tmp_path):
        app = ClusterPilotApp(self._config(), db_path=tmp_path / "jobs.db")
        with self._app_offline(logs_for("0", "50"), {"50": "RUNNING"}):
            async with app.run_test(size=(100, 30)) as pilot:
                view = app.query_one(JobsView)
                await view._do_full_log(a_job()).wait()
                await pilot.pause()
                pane = self._pane_text(app)
                assert "array task 0" in pane
                assert "finished 1 of 2" in pane
                # A finished task's log cannot grow, so it is neither
                # labelled live nor polled.
                assert "live" not in pane
                assert view._tail_timer is None

    @pytest.mark.asyncio
    async def test_a_plain_job_still_tails_its_own_log(self, tmp_path):
        app = ClusterPilotApp(self._config(), db_path=tmp_path / "jobs.db")
        with self._app_offline({}, {}):
            async with app.run_test(size=(100, 30)) as pilot:
                view = app.query_one(JobsView)
                await view._do_tail(a_job(array_spec="")).wait()
                await pilot.pause()
                pane = self._pane_text(app)
                assert "zfc-4123456.out (last 500 lines)" in pane
                assert "array task" not in pane
