"""What the submit screen says when sbatch refuses the job (#75).

A submission was refused on 6 September 2026 with

    sbatch: error: Batch job submission failed: I/O error writing
    script/environment to file

which is the controller failing to write the job to its own spool, and the
TUI reported it as "sbatch failed: sbatch failed: Remote command failed
(exit 1)". Two layers of plumbing, no reason, and it read as a rejected
script. These tests pin what the user is shown instead.

Nothing here touches the network: the daemon, the SSH check, the update
check, the probe, rsync and sbatch itself are all stubbed.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.widgets import Button, Input, TextArea

from clusterpilot.cluster.slurm import SlurmError
from clusterpilot.config import ClusterProfile, Config, Defaults
from clusterpilot.tui.app import ClusterPilotApp
from clusterpilot.tui.submit import SubmitView

TERMINAL_SIZE = (100, 30)

SCRIPT = """#!/bin/bash
#SBATCH --job-name=ising-sweep
#SBATCH --time=02:00:00
#SBATCH --account=def-alice
#SBATCH --partition=compute
#SBATCH --output=%x-%j.out

module load julia/1.11.3
julia --project=. scripts/driver.jl
"""

CONTROLLER_STDERR = (
    "sbatch: error: Batch job submission failed: "
    "I/O error writing script/environment to file"
)


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
def offline_submit(error: SlurmError) -> Iterator[None]:
    """Stub the pipeline and make sbatch fail with *error*."""
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
            patch("clusterpilot.tui.submit.submit", new=AsyncMock(side_effect=error)), \
            patch("clusterpilot.tui.submit.sync_job", new=AsyncMock()):
        yield


async def run_a_failing_submit(
    app: ClusterPilotApp, pilot, project_dir: Path,
) -> tuple[SubmitView, list[str]]:
    """Press SUBMIT on a ready script and collect what the app notified."""
    await pilot.press("f2")
    await pilot.pause()
    view = app.query_one(SubmitView)
    view.query_one("#description-input", TextArea).load_text("Sweep the field.")
    # PROJECT DIR decides where results land, and a blank one means the
    # user's real home rather than the working directory (issue #77).
    view.query_one("#project-dir-input", Input).value = str(project_dir)
    view._generated_script = SCRIPT
    for btn_id in ("#btn-submit", "#btn-edit-script", "#btn-save", "#btn-clear"):
        view.query_one(btn_id, Button).disabled = False

    notices: list[str] = []
    original_notify = app.notify

    def record(message: str, *args, **kwargs):
        notices.append(str(message))
        return original_notify(message, *args, **kwargs)

    with patch.object(app, "notify", record):
        await view._do_submit().wait()
    await pilot.pause()
    return view, notices


class TestSbatchFailureIsReadable:
    @pytest.mark.asyncio
    async def test_the_reason_is_shown_without_a_second_prefix(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        error = SlurmError(
            "Batch job submission failed: I/O error writing script/environment "
            "to file. The scheduler accepted the request and then could not "
            "store it, which is a cluster-side fault, not a problem with the "
            "script. Retry later or ask the site.",
            stderr=CONTROLLER_STDERR,
        )
        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline_submit(error):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                _view, notices = await run_a_failing_submit(app, pilot, tmp_path)

        failure = next(n for n in notices if "I/O error" in n)
        assert "sbatch failed:" not in failure
        assert "cluster-side fault" in failure

    @pytest.mark.asyncio
    async def test_the_raw_output_is_written_beside_the_job(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        error = SlurmError("lgpu is meant for GPU jobs only", stderr=CONTROLLER_STDERR)
        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline_submit(error):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                _view, notices = await run_a_failing_submit(app, pilot, tmp_path)

        logs = list(tmp_path.rglob("sbatch.log"))
        assert len(logs) == 1
        assert logs[0].read_text() == CONTROLLER_STDERR
        assert str(logs[0]) in "\n".join(notices)

    @pytest.mark.asyncio
    async def test_submit_is_re_enabled_so_a_retry_is_possible(
        self, tmp_path: Path, monkeypatch
    ):
        """A cluster-side fault is worth retrying, which needs the button
        back.
        """
        monkeypatch.chdir(tmp_path)
        error = SlurmError("Batch job submission failed", stderr=CONTROLLER_STDERR)
        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline_submit(error):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view, _notices = await run_a_failing_submit(app, pilot, tmp_path)
                assert not view.query_one("#btn-submit", Button).disabled

    @pytest.mark.asyncio
    async def test_a_failure_with_no_stderr_writes_no_log(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        error = SlurmError("sbatch failed: Command timed out after 30.0s")
        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline_submit(error):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                _view, notices = await run_a_failing_submit(app, pilot, tmp_path)

        assert list(tmp_path.rglob("sbatch.log")) == []
        assert any("Command timed out" in n for n in notices)
