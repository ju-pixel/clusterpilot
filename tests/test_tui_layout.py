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
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.widgets import Select

from clusterpilot.cluster.probe import ClusterProbe, PartitionInfo
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
def offline(probe: ClusterProbe | None = None) -> Iterator[None]:
    """Stub out everything that would otherwise reach the network.

    With no *probe*, the cluster probe raises as it would with no connection.
    Pass one to exercise the widgets that are built from probed facts.
    """
    daemon = MagicMock()
    daemon.run_forever = AsyncMock()
    probe_stub = (
        AsyncMock(side_effect=RuntimeError("offline"))
        if probe is None
        else AsyncMock(return_value=probe)
    )
    with patch("clusterpilot.tui.app.PollDaemon", return_value=daemon), \
            patch("clusterpilot.tui.app.is_connected", return_value=False), \
            patch("clusterpilot.update.check_for_update", new=AsyncMock(return_value=None)), \
            patch("clusterpilot.tui.submit.probe_cluster", new=probe_stub), \
            patch("clusterpilot.tui.submit.fetch_availability", new=AsyncMock(return_value={})):
        yield


def narval_probe() -> ClusterProbe:
    """A cut-down Narval probe.

    A MIG node names every profile in one comma-joined GRES field, which is
    the shape ``sinfo -o '%G'`` really returns (#62); the whole card is a
    separate row of the same partition.
    """
    return ClusterProbe(
        cluster_name="testcluster",
        probed_at=time.time(),
        partitions=[
            PartitionInfo(
                "gpubase_bygpu_b1", "3:00:00",
                "gpu:a100_3g.20gb:4,gpu:a100_4g.20gb:1", 141, False,
            ),
            PartitionInfo("gpubase_bygpu_b1", "3:00:00", "gpu:a100:4", 141, False),
            PartitionInfo("cpubase_bycore_b1", "3:00:00", "", 20, True),
        ],
        julia_versions=["julia/1.11.3"],
        accounts=["def-test"],
        account_max_wall={"def-test": ""},
    )


def fir_probe() -> ClusterProbe:
    """A Fir probe, verbatim GRES fields from the live cluster (2026-09-07).

    Three MIG profiles share one row and the whole H100 is a second row, with
    the MIG row leading: the picker must show all four regardless of order.
    """
    return ClusterProbe(
        cluster_name="testcluster",
        probed_at=time.time(),
        partitions=[
            PartitionInfo(
                "gpubase_bygpu_b1", "3:00:00",
                "gpu:nvidia_h100_80gb_hbm3_3g.40gb:4,"
                "gpu:nvidia_h100_80gb_hbm3_2g.20gb:4,"
                "gpu:nvidia_h100_80gb_hbm3_1g.10gb:8",
                60, False, cpus=48, memory_mb=1152000,
            ),
            PartitionInfo(
                "gpubase_bygpu_b1", "3:00:00", "gpu:h100:4",
                30, False, cpus=48, memory_mb=1152000,
            ),
            PartitionInfo("cpubase_bycore_b1", "3:00:00", "", 20, True),
        ],
        julia_versions=["julia/1.11.3"],
        accounts=["def-test"],
        account_max_wall={"def-test": ""},
    )


def cpu_only_probe() -> ClusterProbe:
    return ClusterProbe(
        cluster_name="testcluster",
        probed_at=time.time(),
        partitions=[PartitionInfo("skylake", "7-00:00:00", "", 10, True)],
        julia_versions=["julia/1.11.3"],
        accounts=["def-test"],
        account_max_wall={"def-test": ""},
    )


def select_values(app: ClusterPilotApp, selector: str) -> list[str]:
    """The non-blank option values of a Select, in the order they are shown.

    Select.NULL is the empty sentinel on Textual 8.x; Select.BLANK resolves to
    an unrelated Widget class variable and would not filter anything (#42).
    """
    select = app.query_one(selector, Select)
    return [str(value) for _, value in select._options if value is not Select.NULL]


def select_labels(app: ClusterPilotApp, selector: str) -> list[str]:
    """The option labels of a Select, in the order they are shown."""
    select = app.query_one(selector, Select)
    return [
        str(label) for label, value in select._options if value is not Select.NULL
    ]


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


class TestGpuSizeRow:
    """WP3: the GPU SIZE picker is built from the probe, never from a table
    of GPU names in the code. One partition row can name several profiles, so
    a whole card and its MIG slices arrive side by side.
    """

    @pytest.mark.asyncio
    async def test_every_mig_profile_on_a_row_reaches_the_picker(self, tmp_path: Path):
        """The MIG row leads on Fir, so a parser that keeps only the leading
        entry loses the whole card as well as two slices (#62).
        """
        app = build_app(tmp_path)
        with offline(fir_probe()):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                await pilot.pause()
                assert select_values(app, "#gpu-size-select") == [
                    "h100",
                    "nvidia_h100_80gb_hbm3_1g.10gb",
                    "nvidia_h100_80gb_hbm3_2g.20gb",
                    "nvidia_h100_80gb_hbm3_3g.40gb",
                ]

    @pytest.mark.asyncio
    async def test_slice_labels_are_shortened_but_values_are_not(self, tmp_path: Path):
        """sbatch needs the full profile name, the user does not (#62)."""
        app = build_app(tmp_path)
        with offline(fir_probe()):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                await pilot.pause()
                assert select_labels(app, "#gpu-size-select") == [
                    "h100, whole GPU",
                    "1g.10gb, slice",
                    "2g.20gb, slice",
                    "3g.40gb, slice",
                ]

    @pytest.mark.asyncio
    async def test_the_partition_label_shortens_the_profiles(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline(fir_probe()):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                await pilot.pause()
                labels = select_labels(app, "#partition-select")
                assert labels[0].startswith(
                    "gpubase_bygpu_b1  (GPU: 3g.40gb, 2g.20gb, 1g.10gb  max 3:00:00)"
                )
                assert "nvidia_h100" not in labels[0]

    @pytest.mark.asyncio
    async def test_whole_cards_are_listed_before_slices(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline(narval_probe()):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                await pilot.pause()
                assert select_values(app, "#gpu-size-select") == [
                    "a100", "a100_3g.20gb", "a100_4g.20gb",
                ]

    @pytest.mark.asyncio
    async def test_the_row_is_visible_on_a_gpu_cluster(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline(narval_probe()):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                await pilot.pause()
                assert on_screen(app, "#gpu-size-select")

    @pytest.mark.asyncio
    async def test_the_row_is_hidden_on_a_cpu_only_cluster(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline(cpu_only_probe()):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                await pilot.pause()
                assert app.query_one("#gpu-row").display is False

    @pytest.mark.asyncio
    async def test_the_row_stays_hidden_with_no_probe(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                assert app.query_one("#gpu-row").display is False


class TestHarderJobRow:
    """HARDER JOB picks Opus 5 for one generation. It is a per-job switch, so
    what matters is that it is reachable at the smallest supported terminal and
    that it actually reaches the model argument.
    """

    @pytest.mark.asyncio
    async def test_the_switch_is_on_screen(self, tmp_path: Path):
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                assert on_screen(app, "#opus-switch")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("switched_on", "expected"),
        [(False, "claude-sonnet-5"), (True, "claude-opus-5")],
    )
    async def test_the_switch_chooses_the_model(
        self, tmp_path: Path, switched_on: bool, expected: str,
    ):
        from textual.widgets import Switch

        recorded: dict[str, str] = {}

        def fake_generate_script(*args, **kwargs):
            recorded["model"] = kwargs["model"]

            async def _stream():
                yield "#!/bin/bash\n#SBATCH --job-name=test\necho hi\n"

            return _stream()

        app = build_app(tmp_path)
        with offline(narval_probe()), \
                patch("clusterpilot.tui.submit.generate_script", fake_generate_script):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                app.query_one("#opus-switch", Switch).value = switched_on
                view = app.query_one("SubmitView")
                view._stream_script("run my job")   # type: ignore[attr-defined]
                for _ in range(8):
                    await pilot.pause()

        assert recorded["model"] == expected


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
    async def test_status_bar_legend_follows_the_active_tab(self, tmp_path: Path):
        """WP4: the bottom row lists the keys that work on the screen in front."""
        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                from clusterpilot.tui.app import StatusBar

                bar = app.query_one(StatusBar)
                await pilot.press("f1")
                await pilot.pause()
                assert bar.legend == (
                    "r rsync  k kill  t tail  l log  c clean remote  d forget"
                    "   |   F2 submit  F3 files  F9 config  q quit"
                )
                await pilot.press("f2")
                await pilot.pause()
                assert bar.legend == (
                    "Tab next field  Enter in a picker opens it"
                    "   |   F1 jobs  F3 files  F9 config  q quit"
                )
                await pilot.press("f9")
                await pilot.pause()
                assert bar.legend == (
                    "PgUp PgDn scroll  Enter on EDIT CONFIG opens $EDITOR"
                    "   |   F1 jobs  F2 submit  F3 files  q quit"
                )

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
