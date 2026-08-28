"""Every screen must be usable at 100 columns by 30 rows, keyboard only.

Regression tests for the TUI audit (#32, #33, #36, #39): the config EDIT
button used to be pushed off the bottom of an unfocusable scroll region, the
PARAM TABLE row had no CSS and could collapse to nothing, the description box
showed about two lines, and the six action buttons on F1 clipped.

Nothing here touches the network: the poll daemon, the SSH connection check,
the PyPI update check and the cluster probe are all stubbed.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clusterpilot.config import ClusterProfile, Config, Defaults
from clusterpilot.tui.app import ClusterPilotApp

TERMINAL_SIZE = (100, 30)


def stub_config() -> Config:
    """A minimal one-cluster config, enough to compose every screen."""
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


def build_app(tmp_path: Path) -> ClusterPilotApp:
    return ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")


def on_screen(app: ClusterPilotApp, selector: str) -> bool:
    """True when the widget has a real size and sits inside the terminal."""
    region = app.query_one(selector).region
    return (
        region.width > 0
        and region.height > 0
        and region.x >= 0
        and region.y >= 0
        and region.right <= app.size.width
        and region.bottom <= app.size.height
    )


class TestConfigScreen:
    @pytest.mark.asyncio
    async def test_edit_button_stays_on_screen(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f9")
                await pilot.pause()
                assert on_screen(app, "#btn-edit-config")

    @pytest.mark.asyncio
    async def test_config_text_can_be_scrolled_from_the_keyboard(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f9")
                await pilot.pause()
                assert app.query_one("#config-scroll").can_focus


class TestSubmitScreen:
    @pytest.mark.asyncio
    async def test_param_table_field_is_visible(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                assert app.query_one("#params-table-input").region.height > 0

    @pytest.mark.asyncio
    async def test_description_box_is_eight_rows(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                assert app.query_one("#description-input").region.height == 8

    @pytest.mark.asyncio
    async def test_help_panel_height_is_fixed(self, tmp_path: Path):
        """A changing help height used to move the GENERATE button under the cursor."""
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                assert app.query_one("#field-help").region.height == 3


class TestJobsScreen:
    @pytest.mark.asyncio
    async def test_all_six_action_buttons_fit(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f1")
                await pilot.pause()
                for button in (
                    "#btn-rsync", "#btn-kill", "#btn-tail",
                    "#btn-log", "#btn-clean", "#btn-delete",
                ):
                    assert on_screen(app, button), f"{button} is clipped"

    @pytest.mark.asyncio
    async def test_all_four_submit_buttons_fit(self, tmp_path: Path):
        # #40: SUBMIT, EDIT, SAVE and CLEAR must all be visible at 100 columns.
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                for button in ("#btn-submit", "#btn-edit-script", "#btn-save", "#btn-clear"):
                    assert on_screen(app, button), f"{button} is clipped"

    @pytest.mark.asyncio
    async def test_hint_bar_sits_above_the_status_bar(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.pause()
                from clusterpilot.tui.app import HintBar, StatusBar
                hint = app.query_one(HintBar).region
                status = app.query_one(StatusBar).region
                assert hint.height == 1
                assert hint.y == status.y - 1
