"""After a submit, F1 opens on the new job and F2 is ready for the next run.

WP4 of the TUI audit. Before this, submitting switched to F1 with whatever
row happened to be selected still selected, and left the spent script sitting
in the F2 pane with SUBMIT still lit, so a second press resubmitted it.

Nothing here touches the network: the daemon, the SSH check, the PyPI update
check, the cluster probe, rsync and sbatch are all stubbed. The job database
is a real SQLite file under tmp_path, because the hand-off reads back the row
the submit wrote.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.widgets import Button, TextArea

from clusterpilot.config import ClusterProfile, Config, Defaults
from clusterpilot.tui.app import ClusterPilotApp
from clusterpilot.tui.jobs import JobsView
from clusterpilot.tui.submit import SubmitView

TERMINAL_SIZE = (100, 30)

JOB_ID = "4123456"

SCRIPT = """#!/bin/bash
#SBATCH --job-name=ising-sweep
#SBATCH --time=02:00:00
#SBATCH --account=def-alice
#SBATCH --partition=compute
#SBATCH --output=%x-%j.out

module load julia/1.11.3
julia --project=. scripts/driver.jl
"""

DESCRIPTION = "Sweep the Ising temperature range.\nTwo hours is plenty."


def stub_config() -> Config:
    return Config(
        defaults=Defaults(api_key="test-key"),
        clusters=[
            ClusterProfile(
                name="testcluster",
                host="test.example.org",
                user="tester",
                account="def-alice",
                scratch="$HOME/scratch",
                cluster_type="generic",
            )
        ],
    )


@contextlib.contextmanager
def offline_submit() -> Iterator[None]:
    """Stub the daemon, the probe, and every step of the submit pipeline."""
    daemon = MagicMock()
    daemon.run_forever = AsyncMock()
    with patch("clusterpilot.tui.app.PollDaemon", return_value=daemon), \
            patch("clusterpilot.tui.app.is_connected", return_value=False), \
            patch("clusterpilot.update.check_for_update", new=AsyncMock(return_value=None)), \
            patch(
                "clusterpilot.tui.submit.probe_cluster",
                new=AsyncMock(side_effect=RuntimeError("offline")),
            ), \
            patch("clusterpilot.tui.submit.fetch_availability", new=AsyncMock(return_value={})), \
            patch("clusterpilot.tui.submit.run_remote", new=AsyncMock(return_value="")), \
            patch("clusterpilot.tui.submit.upload", new=AsyncMock()), \
            patch("clusterpilot.tui.submit.upload_file", new=AsyncMock()), \
            patch("clusterpilot.tui.submit.submit", new=AsyncMock(return_value=JOB_ID)), \
            patch("clusterpilot.tui.submit.sync_job", new=AsyncMock()):
        yield


async def run_a_submit(app: ClusterPilotApp, pilot) -> SubmitView:
    """Fill in F2 with a ready-to-submit script and press SUBMIT."""
    await pilot.press("f2")
    await pilot.pause()
    view = app.query_one(SubmitView)
    view.query_one("#description-input", TextArea).load_text(DESCRIPTION)
    view._generated_script = SCRIPT
    for btn_id in ("#btn-submit", "#btn-edit-script", "#btn-save", "#btn-clear"):
        view.query_one(btn_id, Button).disabled = False
    # Call the worker directly rather than pressing the button, so the test can
    # await exactly this worker instead of every worker the app has running.
    view.query_one("#btn-submit", Button).disabled = True
    await view._do_submit().wait()
    await pilot.pause()
    return view


class TestSubmitHandsOverToJobs:
    @pytest.mark.asyncio
    async def test_f1_opens_on_the_new_job(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline_submit():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await run_a_submit(app, pilot)
                jobs = app.query_one(JobsView)
                assert jobs._jobs, "the submitted job never reached the list"
                assert jobs._jobs[jobs._selected].job_id == JOB_ID
                assert "ising-sweep" in str(app.query_one("#meta-content").content)
                assert JOB_ID in str(app.query_one("#meta-title").content)

    @pytest.mark.asyncio
    async def test_the_spent_script_is_cleared_but_the_description_stays(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline_submit():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await run_a_submit(app, pilot)
                assert view._generated_script == ""
                assert view._findings == []
                for btn_id in (
                    "#btn-submit", "#btn-edit-script", "#btn-save", "#btn-clear",
                ):
                    assert view.query_one(btn_id, Button).disabled, btn_id
                assert (
                    view.query_one("#description-input", TextArea).text == DESCRIPTION
                )


class TestClearButton:
    @pytest.mark.asyncio
    async def test_clear_drops_the_description_and_the_script_only(
        self, tmp_path: Path
    ):
        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline_submit():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                view = app.query_one(SubmitView)
                view.query_one("#description-input", TextArea).load_text(DESCRIPTION)
                view.query_one("#array-input").value = "0-9"
                view.query_one("#project-dir-input").value = "/tmp/project"
                view._generated_script = SCRIPT
                view.on_clear()
                await pilot.pause()
                assert view._generated_script == ""
                assert view.query_one("#description-input", TextArea).text == ""
                assert view.query_one("#array-input").value == "0-9"
                assert view.query_one("#project-dir-input").value == "/tmp/project"
