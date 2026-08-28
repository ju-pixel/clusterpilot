"""Destructive F1 actions must be reachable by key and must confirm first.

Regression tests for the TUI audit (#34, #37, #38): the buttons advertised
[R] [K] [T] [L] [C] [D] but no key bindings existed, KILL and FORGET fired on
a single press, and `q` quit instantly even with jobs still on the cluster.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from textual.widgets import Static

from clusterpilot.config import ClusterProfile, Config, Defaults
from clusterpilot.db import JobRecord
from clusterpilot.tui.app import ClusterPilotApp
from clusterpilot.tui.jobs import JobsView
from clusterpilot.tui.widgets.confirm import ConfirmScreen

TERMINAL_SIZE = (100, 30)


def stub_config() -> Config:
    return Config(
        defaults=Defaults(api_key="test-key"),
        clusters=[
            ClusterProfile(
                name="testcluster",
                host="test.example.org",
                user="tester",
                account="def-test",
                scratch="$HOME/scratch",
                cluster_type="generic",
            )
        ],
    )


def running_job() -> JobRecord:
    return JobRecord(
        job_id="12345",
        job_name="spin_glass_sweep",
        cluster_name="testcluster",
        host="test.example.org",
        user="tester",
        account="def-test",
        partition="gpu",
        script_path="/tmp/job.sh",
        working_dir="/scratch/tester/spin_glass_sweep",
        local_dir="/tmp/spin_glass_sweep",
        walltime="04:00:00",
        status="RUNNING",
    )


@contextlib.contextmanager
def offline() -> Iterator[None]:
    """Stub out everything that would otherwise reach the network."""
    daemon = MagicMock()
    daemon.run_forever = AsyncMock()
    with patch("clusterpilot.tui.app.PollDaemon", return_value=daemon), \
            patch("clusterpilot.tui.app.is_connected", return_value=False), \
            patch("clusterpilot.update.check_for_update", new=AsyncMock(return_value=None)), \
            patch(
                "clusterpilot.tui.submit.probe_cluster",
                new=AsyncMock(side_effect=RuntimeError("offline")),
            ), \
            patch("clusterpilot.tui.submit.fetch_availability", new=AsyncMock(return_value={})):
        yield


def confirm_body(app: ClusterPilotApp) -> str:
    """The body text of the confirmation modal currently on top."""
    return str(app.screen.query_one("#confirm-body", Static).content)


def build_app(tmp_path: Path) -> ClusterPilotApp:
    return ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")


def inject_running_job(app: ClusterPilotApp) -> JobsView:
    """Put one RUNNING job into the F1 list without touching a database."""
    view = app.query_one(JobsView)
    view._jobs = [running_job()]
    view._selected = 0
    view._rebuild_list()
    view.focus_job_list()
    return view


class TestKillConfirmation:
    @pytest.mark.asyncio
    async def test_k_opens_the_confirmation(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline(), patch("clusterpilot.tui.jobs.cancel", new=AsyncMock()) as cancel:
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                inject_running_job(app)
                await pilot.pause()
                await pilot.press("k")
                await pilot.pause()
                assert isinstance(app.screen, ConfirmScreen)
                assert "12345" in confirm_body(app)
                cancel.assert_not_called()

    @pytest.mark.asyncio
    async def test_escape_cancels_without_killing_anything(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline(), patch("clusterpilot.tui.jobs.cancel", new=AsyncMock()) as cancel:
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                inject_running_job(app)
                await pilot.pause()
                await pilot.press("k")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(app.screen, ConfirmScreen)
                cancel.assert_not_called()


class TestCleanAndForgetConfirmation:
    @pytest.mark.asyncio
    async def test_c_names_the_remote_directory(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                inject_running_job(app)
                await pilot.pause()
                await pilot.press("c")
                await pilot.pause()
                assert isinstance(app.screen, ConfirmScreen)
                body = confirm_body(app)
                assert "/scratch/tester/spin_glass_sweep" in body
                assert "testcluster" in body

    @pytest.mark.asyncio
    async def test_d_on_a_running_job_refuses_rather_than_confirming(self, tmp_path: Path):
        """FORGET is refused outright for an active job, as it was before."""
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                inject_running_job(app)
                await pilot.pause()
                await pilot.press("d")
                await pilot.pause()
                assert not isinstance(app.screen, ConfirmScreen)


class TestQuitConfirmation:
    @pytest.mark.asyncio
    async def test_q_confirms_while_a_job_is_running(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                inject_running_job(app)
                await pilot.pause()
                await pilot.press("q")
                await pilot.pause()
                assert isinstance(app.screen, ConfirmScreen)
                assert app.is_running

    @pytest.mark.asyncio
    async def test_q_quits_when_nothing_is_running(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.pause()
                await pilot.press("q")
                await pilot.pause()
                assert not isinstance(app.screen, ConfirmScreen)
                assert app._exit
