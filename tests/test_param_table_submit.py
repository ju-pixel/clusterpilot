"""The parameter-table array path, end to end on the F2 Submit screen.

A real 70-task array was blocked on 31 August 2026 by four separate faults on
this one path, and every one of them was silent about what it had done:

* #58 the F3 file picker wrote the chosen table into EXTRA FILES rather than
  into the focused PARAM TABLE field, so the whole parameter-table path was
  skipped and the model improvised a reader from the prose description
* #52 the driver-uploaded check was handed the EXTRA FILES field instead of
  the set the uploader actually sends, so a correct script was blocked
* #53 EDIT never re-validated, so the block could not be cleared
* #54 nothing confirmed the rendered reader had reached the emitted script
* #51 a blank ARRAY field with a table lost the per-task log names

Nothing here touches the network: the daemon, the SSH check, the update check,
the cluster probe and the model call are all stubbed. The generated script is
canned, because what is under test is everything ClusterPilot does around it.
"""
from __future__ import annotations

import contextlib
import subprocess
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.widgets import Button, Input, TextArea

from clusterpilot.cluster.probe import ClusterProbe, PartitionInfo
from clusterpilot.config import ClusterProfile, Config, Defaults
from clusterpilot.jobs.params_table import load_params_table, render_bash_reader
from clusterpilot.tui.app import ClusterPilotApp
from clusterpilot.tui.submit import SubmitView
from clusterpilot.tui.widgets.file_explorer import FileExplorer

TERMINAL_SIZE = (100, 30)

DRIVER = "scripts/drivers/run_zfc_ewald.jl"

# The header of the table that was blocked, columns and all.
TABLE_HEADER = (
    "task_id\tSGL_LATTICE\tSGL_ETA\tSGL_HSTAR\tSGL_SEED_BASE\tSGL_BOX_PARITY"
)


def stub_config() -> Config:
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


def stub_probe() -> ClusterProbe:
    return ClusterProbe(
        cluster_name="rorqual",
        probed_at=0.0,
        partitions=[
            PartitionInfo("gpubase_bygpu_b1", "1-00:00:00", "gpu:h100:4", 100, False),
        ],
        julia_versions=["julia/1.10.10"],
        accounts=["def-stamps"],
        account_max_wall={"def-stamps": ""},
    )


def write_project(root: Path, *, rows: int = 70) -> Path:
    """A Julia project with a driver and a parameter table, as on the day."""
    (root / "Project.toml").write_text('name = "SpinGlassLab"\n')
    (root / "Manifest.toml").write_text("\n")
    (root / "src").mkdir()
    (root / "src" / "SpinGlassLab.jl").write_text("module SpinGlassLab\nend\n")
    (root / "scripts" / "drivers").mkdir(parents=True)
    (root / DRIVER).write_text("println(1)\n")

    table_dir = root / "experiments" / "tc_t0_crossover"
    table_dir.mkdir(parents=True)
    table = table_dir / "field_sweep_cubic_rorqual_params.tsv"
    body = [TABLE_HEADER]
    for task in range(rows):
        body.append(f"{task}\tcubic\t0.30\t{task * 0.01:.2f}\t{1000 + task}\teven")
    table.write_text("\n".join(body) + "\n")
    return table


def canned_script(table_name: str, *, reader: str = "", body: str = "") -> str:
    """A DRAC array script, optionally carrying the rendered reader."""
    return (
        "#!/bin/bash\n"
        "#SBATCH --job-name=zfc-field-sweep-cubic\n"
        "#SBATCH --account=def-stamps\n"
        "#SBATCH --array=0-69\n"
        "#SBATCH --time=24:00:00\n"
        "#SBATCH --cpus-per-task=1\n"
        "#SBATCH --mem=4G\n"
        "#SBATCH --gres=gpu:h100_3g.40gb:1\n"
        "#SBATCH --output=%x-%A-%a.out\n"
        "\n"
        "module load julia/1.10.10\n"
        "module load cuda/12.2\n"
        "\n"
        f"{reader}"
        f"{body}"
        f"julia --project=. {DRIVER}\n"
    )


@contextlib.contextmanager
def offline(script: str) -> Iterator[None]:
    """Stub the network and hand *script* back from the model call."""
    daemon = MagicMock()
    daemon.run_forever = AsyncMock()

    def fake_generate(*args, **kwargs):
        async def stream():
            yield script
        return stream()

    with patch("clusterpilot.tui.app.PollDaemon", return_value=daemon), \
            patch("clusterpilot.tui.app.is_connected", return_value=False), \
            patch("clusterpilot.update.check_for_update", new=AsyncMock(return_value=None)), \
            patch(
                "clusterpilot.tui.submit.probe_cluster",
                new=AsyncMock(return_value=stub_probe()),
            ), \
            patch("clusterpilot.tui.submit.fetch_availability", new=AsyncMock(return_value={})), \
            patch("clusterpilot.tui.submit.generate_script", new=fake_generate):
        yield


async def open_submit(app: ClusterPilotApp, pilot) -> SubmitView:
    await pilot.press("f2")
    await pilot.pause()
    return app.query_one(SubmitView)


async def generate(view: SubmitView, pilot, description: str = "Sweep the field.") -> None:
    """Run one generation, awaiting exactly that worker."""
    view.query_one("#description-input", TextArea).load_text(description)
    await view._stream_script(description).wait()
    await pilot.pause()


def slugs(view: SubmitView) -> list[str]:
    return [f.check for f in view._findings]


# ── #58: the picker puts a file in the field the user is in ───────────────────

class TestFilePickerRouting:
    @pytest.mark.asyncio
    async def test_a_table_chosen_with_param_table_focused_lands_there(
        self, tmp_path: Path
    ):
        table = write_project(tmp_path, rows=3)
        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline(""):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await open_submit(app, pilot)
                view.query_one("#project-dir-input", Input).value = str(tmp_path)
                view.query_one("#script-path-input", Input).value = DRIVER
                view.query_one("#params-table-input", Input).focus()
                await pilot.pause()

                app.post_message(FileExplorer.FileSelected(table))
                await pilot.pause()

                assert view.query_one("#params-table-input", Input).value == (
                    "experiments/tc_t0_crossover/field_sweep_cubic_rorqual_params.tsv"
                )
                assert view.query_one("#extra-files-input", Input).value == ""

    @pytest.mark.asyncio
    async def test_extra_files_still_appends_when_it_is_the_focused_field(
        self, tmp_path: Path
    ):
        write_project(tmp_path, rows=3)
        (tmp_path / "a.jld2").write_text("x")
        (tmp_path / "b.jld2").write_text("y")
        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline(""):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await open_submit(app, pilot)
                view.query_one("#project-dir-input", Input).value = str(tmp_path)
                view.query_one("#extra-files-input", Input).focus()
                await pilot.pause()

                app.post_message(FileExplorer.FileSelected(tmp_path / "a.jld2"))
                await pilot.pause()
                app.post_message(FileExplorer.FileSelected(tmp_path / "b.jld2"))
                await pilot.pause()

                assert view.query_one("#extra-files-input", Input).value == (
                    "a.jld2, b.jld2"
                )
                assert view.query_one("#params-table-input", Input).value == ""

    @pytest.mark.asyncio
    async def test_the_same_file_is_not_queued_twice(self, tmp_path: Path):
        (tmp_path / "Project.toml").write_text('name = "X"\n')
        (tmp_path / "a.jld2").write_text("x")
        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline(""):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await open_submit(app, pilot)
                view.query_one("#project-dir-input", Input).value = str(tmp_path)
                view.query_one("#extra-files-input", Input).focus()
                await pilot.pause()
                app.post_message(FileExplorer.FileSelected(tmp_path / "a.jld2"))
                await pilot.pause()
                app.post_message(FileExplorer.FileSelected(tmp_path / "a.jld2"))
                await pilot.pause()
                assert view.query_one("#extra-files-input", Input).value == "a.jld2"

    @pytest.mark.asyncio
    async def test_the_driver_field_takes_a_project_relative_path(self, tmp_path: Path):
        write_project(tmp_path, rows=3)
        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline(""):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await open_submit(app, pilot)
                view.query_one("#project-dir-input", Input).value = str(tmp_path)
                view.query_one("#script-path-input", Input).focus()
                await pilot.pause()
                app.post_message(FileExplorer.FileSelected(tmp_path / DRIVER))
                await pilot.pause()
                assert view.query_one("#script-path-input", Input).value == DRIVER

    @pytest.mark.asyncio
    async def test_an_untouched_form_still_fills_project_dir_and_driver(
        self, tmp_path: Path
    ):
        """The old fill-the-first-empty behaviour, kept for a fresh form."""
        write_project(tmp_path, rows=3)
        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline(""):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await open_submit(app, pilot)
                view._last_path_field = ""
                app.post_message(FileExplorer.FileSelected(tmp_path / DRIVER))
                await pilot.pause()
                assert view.query_one("#project-dir-input", Input).value == str(
                    (tmp_path / DRIVER).parent
                )
                assert view.query_one("#script-path-input", Input).value == (
                    "run_zfc_ewald.jl"
                )


# ── the reproduction from the fix brief ───────────────────────────────────────

class TestTheBlockedArray:
    @pytest.mark.asyncio
    async def test_a_seventy_task_array_generates_and_is_submittable(
        self, tmp_path: Path
    ):
        table_path = write_project(tmp_path)
        table = load_params_table(table_path)
        script = canned_script(table_path.name, reader=render_bash_reader(table) + "\n")

        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline(script):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await open_submit(app, pilot)
                view.query_one("#project-dir-input", Input).value = str(tmp_path)
                view.query_one("#script-path-input", Input).value = DRIVER
                view.query_one("#params-table-input", Input).value = str(
                    table_path.relative_to(tmp_path)
                )
                view.query_one("#array-input", Input).value = "0-69"
                await generate(view, pilot)

                assert view._findings == [], [f.message for f in view._findings]
                assert not view.query_one("#btn-submit", Button).disabled
                assert view._params_table is not None
                assert view._params_table.task_count == 70
                assert "--output=%x-%A-%a.out" in view._generated_script

    @pytest.mark.asyncio
    async def test_the_five_parameter_columns_reach_every_task(self, tmp_path: Path):
        table_path = write_project(tmp_path)
        table = load_params_table(table_path)
        reader = render_bash_reader(table)
        for column in (
            "SGL_LATTICE", "SGL_ETA", "SGL_HSTAR", "SGL_SEED_BASE", "SGL_BOX_PARITY",
        ):
            assert f"export {column}=" in reader

    def test_the_block_the_prompt_asks_for_is_the_block_the_check_wants(
        self, tmp_path: Path
    ):
        """The prompt indents the reader; the validator must still accept it.

        The two call render_bash_reader with different indents, so this is the
        seam where a strict check could reject every generation.
        """
        from clusterpilot.jobs import validate
        from clusterpilot.jobs.validate import SubmitIntent

        table_path = write_project(tmp_path, rows=4)
        table = load_params_table(table_path)
        as_prompted = render_bash_reader(table, indent="   ")
        script = canned_script(table_path.name, reader=as_prompted + "\n")
        intent = SubmitIntent(
            param_reader=render_bash_reader(table),
            param_columns=tuple(table.headers),
        )
        assert validate._check_params_reader(script, intent) == []

    @pytest.mark.asyncio
    async def test_an_extra_file_no_longer_blocks_a_correct_script(
        self, tmp_path: Path
    ):
        """#52 in situ: EXTRA FILES naming something else is not a block."""
        table_path = write_project(tmp_path)
        table = load_params_table(table_path)
        script = canned_script(table_path.name, reader=render_bash_reader(table) + "\n")
        (tmp_path / "notes.md").write_text("x")

        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline(script):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await open_submit(app, pilot)
                view.query_one("#project-dir-input", Input).value = str(tmp_path)
                view.query_one("#script-path-input", Input).value = DRIVER
                view.query_one("#extra-files-input", Input).value = "notes.md"
                view.query_one("#params-table-input", Input).value = str(
                    table_path.relative_to(tmp_path)
                )
                view.query_one("#array-input", Input).value = "0-69"
                await generate(view, pilot)

                assert "driver-not-uploaded" not in slugs(view)
                assert not view.query_one("#btn-submit", Button).disabled

    @pytest.mark.asyncio
    async def test_an_improvised_reader_blocks_the_submit(self, tmp_path: Path):
        """#54: the failure that would have run 70 tasks on the wrong values."""
        table_path = write_project(tmp_path)
        script = canned_script(
            table_path.name,
            body=(
                'export SGL_LATTICE=cubi\n'
                'read -r a b < <(sed -n "$((SLURM_ARRAY_TASK_ID + 2))p" '
                f'{table_path.name})\n'
            ),
        )
        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline(script):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await open_submit(app, pilot)
                view.query_one("#project-dir-input", Input).value = str(tmp_path)
                view.query_one("#script-path-input", Input).value = DRIVER
                view.query_one("#params-table-input", Input).value = str(
                    table_path.relative_to(tmp_path)
                )
                view.query_one("#array-input", Input).value = "0-69"
                await generate(view, pilot)

                assert "params-reader-missing" in slugs(view)
                assert view.query_one("#btn-submit", Button).disabled


# ── #51: a blank ARRAY field is filled in from the table ──────────────────────

class TestArraySpecWriteBack:
    @pytest.mark.asyncio
    async def test_the_derived_spec_reaches_the_field_submit_reads(
        self, tmp_path: Path
    ):
        table_path = write_project(tmp_path, rows=12)
        table = load_params_table(table_path)
        script = canned_script(
            table_path.name, reader=render_bash_reader(table) + "\n"
        ).replace("--array=0-69", "--array=0-11")

        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline(script):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await open_submit(app, pilot)
                view.query_one("#project-dir-input", Input).value = str(tmp_path)
                view.query_one("#script-path-input", Input).value = DRIVER
                view.query_one("#params-table-input", Input).value = str(
                    table_path.relative_to(tmp_path)
                )
                view.query_one("#array-input", Input).value = ""
                await generate(view, pilot)

                assert view.query_one("#array-input", Input).value == "0-11"

    @pytest.mark.asyncio
    async def test_an_explicit_array_field_is_left_alone(self, tmp_path: Path):
        table_path = write_project(tmp_path, rows=12)
        table = load_params_table(table_path)
        script = canned_script(
            table_path.name, reader=render_bash_reader(table) + "\n"
        ).replace("--array=0-69", "--array=0-3")

        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline(script):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await open_submit(app, pilot)
                view.query_one("#project-dir-input", Input).value = str(tmp_path)
                view.query_one("#script-path-input", Input).value = DRIVER
                view.query_one("#params-table-input", Input).value = str(
                    table_path.relative_to(tmp_path)
                )
                view.query_one("#array-input", Input).value = "0-3"
                await generate(view, pilot)
                assert view.query_one("#array-input", Input).value == "0-3"


# ── #53: EDIT re-runs the checks, both ways ──────────────────────────────────

class TestEditRevalidates:
    @pytest.mark.asyncio
    async def test_editing_out_the_offending_line_clears_the_block(
        self, tmp_path: Path
    ):
        table_path = write_project(tmp_path, rows=4)
        table = load_params_table(table_path)
        reader = render_bash_reader(table) + "\n"
        blocked = canned_script(
            table_path.name,
            reader=reader,
            body='case "$SLURM_ARRAY_TASK_ID" in\n  *) SGL_ETA=0.9 ;;\nesac\n',
        ).replace("--array=0-69", "--array=0-3")
        fixed = canned_script(table_path.name, reader=reader).replace(
            "--array=0-69", "--array=0-3"
        )

        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline(blocked):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await open_submit(app, pilot)
                view.query_one("#project-dir-input", Input).value = str(tmp_path)
                view.query_one("#script-path-input", Input).value = DRIVER
                view.query_one("#params-table-input", Input).value = str(
                    table_path.relative_to(tmp_path)
                )
                view.query_one("#array-input", Input).value = "0-3"
                await generate(view, pilot)

                assert "params-reader-competing" in slugs(view)
                assert view.query_one("#btn-submit", Button).disabled

                # What EDIT does once the editor has written the file back.
                view._generated_script = fixed
                view._apply_validation(announce_clean=True)
                await pilot.pause()

                assert view._findings == [], [f.message for f in view._findings]
                assert not view.query_one("#btn-submit", Button).disabled

    @pytest.mark.asyncio
    async def test_editing_a_clean_script_into_a_broken_one_blocks_it(
        self, tmp_path: Path
    ):
        table_path = write_project(tmp_path, rows=4)
        table = load_params_table(table_path)
        reader = render_bash_reader(table) + "\n"
        clean = canned_script(table_path.name, reader=reader).replace(
            "--array=0-69", "--array=0-3"
        )
        broken = canned_script(table_path.name).replace("--array=0-69", "--array=0-3")

        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline(clean):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await open_submit(app, pilot)
                view.query_one("#project-dir-input", Input).value = str(tmp_path)
                view.query_one("#script-path-input", Input).value = DRIVER
                view.query_one("#params-table-input", Input).value = str(
                    table_path.relative_to(tmp_path)
                )
                view.query_one("#array-input", Input).value = "0-3"
                await generate(view, pilot)
                assert not view.query_one("#btn-submit", Button).disabled

                view._generated_script = broken
                view._apply_validation(announce_clean=True)
                await pilot.pause()

                assert "params-reader-missing" in slugs(view)
                assert view.query_one("#btn-submit", Button).disabled

    @pytest.mark.asyncio
    async def test_the_edit_button_runs_the_gate(self, tmp_path: Path, monkeypatch):
        """The handler itself, with the editor subprocess stubbed out."""
        table_path = write_project(tmp_path, rows=4)
        table = load_params_table(table_path)
        reader = render_bash_reader(table) + "\n"
        blocked = canned_script(table_path.name).replace("--array=0-69", "--array=0-3")
        fixed = canned_script(table_path.name, reader=reader).replace(
            "--array=0-69", "--array=0-3"
        )

        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline(blocked):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await open_submit(app, pilot)
                view.query_one("#project-dir-input", Input).value = str(tmp_path)
                view.query_one("#script-path-input", Input).value = DRIVER
                view.query_one("#params-table-input", Input).value = str(
                    table_path.relative_to(tmp_path)
                )
                view.query_one("#array-input", Input).value = "0-3"
                await generate(view, pilot)
                assert view.query_one("#btn-submit", Button).disabled

                real_run = subprocess.run

                def fake_editor(argv, *args, **kwargs):
                    """Stand in for the editor, and only for the editor.

                    The validator shells out to ``bash -n`` through the same
                    module attribute, so anything that is not the two-argument
                    editor call is passed straight through. Swallowing it
                    instead would quietly disable the syntax check this test
                    depends on, and write a file called "-n" into the repo.
                    """
                    if len(argv) == 2 and str(argv[1]).endswith(".sh"):
                        Path(argv[1]).write_text(fixed)
                        return MagicMock(returncode=0)
                    return real_run(argv, *args, **kwargs)

                with patch("clusterpilot.tui.submit.subprocess.run", fake_editor), \
                        patch.object(app, "suspend", contextlib.nullcontext):
                    view.on_edit_script()
                await pilot.pause()

                assert view._generated_script == fixed
                assert view._findings == [], [f.message for f in view._findings]
                assert not view.query_one("#btn-submit", Button).disabled


# ── #60: a fixed export that shadows a table column ──────────────────────────

class TestShadowedColumnWarns:
    @pytest.mark.asyncio
    async def test_a_fixed_export_of_a_column_warns_without_blocking(
        self, tmp_path: Path
    ):
        table_path = write_project(tmp_path, rows=4)
        table = load_params_table(table_path)
        script = canned_script(
            table_path.name,
            reader=render_bash_reader(table) + "\n",
            body="export SGL_LATTICE=cubi\n",
        ).replace("--array=0-69", "--array=0-3")

        app = ClusterPilotApp(stub_config(), db_path=tmp_path / "jobs.db")
        with offline(script):
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                view = await open_submit(app, pilot)
                view.query_one("#project-dir-input", Input).value = str(tmp_path)
                view.query_one("#script-path-input", Input).value = DRIVER
                view.query_one("#params-table-input", Input).value = str(
                    table_path.relative_to(tmp_path)
                )
                view.query_one("#array-input", Input).value = "0-3"
                await generate(view, pilot)

                assert slugs(view) == ["params-column-shadowed"]
                assert not view.query_one("#btn-submit", Button).disabled
