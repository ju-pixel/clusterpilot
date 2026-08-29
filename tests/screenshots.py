"""Regenerate the README screenshots from a stubbed app. Not a test.

Run it from the repository root with the project's virtualenv:

    .venv/bin/python tests/screenshots.py

It builds the TUI headlessly at 120x36 against a made-up config (clusters
``grex`` and ``narval``) and a throwaway SQLite database of five made-up jobs,
captures F1, F2 and F9 as SVG into ``docs/screenshots/``, then renders each one
to a 2x PNG with the resvg build already vendored under
``frontend/node_modules``. Nothing here touches the network, the real config,
the real job database or a real cluster, and no real username, account or
hostname appears in the output.

Pass ``--no-png`` to stop after the SVGs.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from clusterpilot.cluster.probe import (  # noqa: E402
    ClusterProbe,
    PartitionAvailability,
    PartitionInfo,
)
from clusterpilot.config import ClusterProfile, Config, Defaults  # noqa: E402
from clusterpilot.db import JobRecord, init_db, insert_job  # noqa: E402
from clusterpilot.tui.app import ClusterPilotApp  # noqa: E402
from clusterpilot.tui.jobs import JobsView  # noqa: E402
from clusterpilot.tui.submit import SubmitView, _format_script  # noqa: E402

OUT_DIR = REPO_ROOT / "docs" / "screenshots"
RESVG = REPO_ROOT / "frontend" / "node_modules" / "@resvg" / "resvg-js"
SIZE = (120, 36)

# Everything is dated relative to now, so the RUNNING job shows a believable
# elapsed time rather than one measured from a frozen epoch.
NOW = time.time()


def demo_config() -> Config:
    """Two invented clusters: a Grex-like one and a DRAC-like one."""
    return Config(
        defaults=Defaults(api_key="sk-ant-demo-not-a-real-key"),
        clusters=[
            ClusterProfile(
                name="grex",
                host="login.example.ca",
                user="alice",
                account="",
                scratch="/home/alice",
                cluster_type="grex",
            ),
            ClusterProfile(
                name="narval",
                host="narval.example.ca",
                user="alice",
                account="def-alice",
                scratch="/scratch/alice",
                cluster_type="drac",
            ),
        ],
    )


def demo_jobs() -> list[tuple[JobRecord, float | None, float | None, bool]]:
    """Five invented jobs, one per interesting status.

    Each entry is (record, started_at, finished_at, synced): ``insert_job``
    writes neither the timestamps nor the sync flag, so the caller patches
    them in afterwards.
    """
    def record(**kwargs) -> JobRecord:
        base = dict(
            host="login.example.ca",
            user="alice",
            account="def-alice",
            script_path="/scratch/alice/job.sh",
            local_dir="/home/alice/projects/spinglass",
            walltime="04:00:00",
            model_used="claude-sonnet-5",
            input_tokens=5_200,
            output_tokens=1_150,
        )
        base.update(kwargs)
        return JobRecord(**base)  # type: ignore[arg-type]

    return [
        (
            record(
                job_id="4137812",
                job_name="ising-sweep",
                cluster_name="narval",
                partition="gpubase_bygpu_b1",
                working_dir="/scratch/alice/clusterpilot_jobs/ising-sweep",
                status="RUNNING",
                status_detail="3R/5PD",
                array_spec="0-7",
                submitted_at=NOW - 7_400,
            ),
            NOW - 7_100, None, False,
        ),
        (
            record(
                job_id="4137905",
                job_name="zfc-cooling",
                cluster_name="narval",
                partition="gpubase_bygpu_b1",
                working_dir="/scratch/alice/clusterpilot_jobs/zfc-cooling",
                status="PENDING",
                walltime="12:00:00",
                submitted_at=NOW - 900,
            ),
            None, None, False,
        ),
        (
            record(
                job_id="4136440",
                job_name="replica-exchange",
                cluster_name="grex",
                partition="skylake",
                working_dir="/home/alice/clusterpilot_jobs/replica-exchange",
                status="COMPLETED",
                walltime="08:00:00",
                submitted_at=NOW - 90_000,
            ),
            NOW - 89_400, NOW - 61_200, True,
        ),
        (
            record(
                job_id="4135277",
                job_name="hysteresis-loop",
                cluster_name="grex",
                partition="lgpu",
                working_dir="/home/alice/clusterpilot_jobs/hysteresis-loop",
                status="FAILED",
                walltime="02:00:00",
                submitted_at=NOW - 172_000,
            ),
            NOW - 171_800, NOW - 171_100, True,
        ),
        (
            record(
                job_id="4134019",
                job_name="anisotropy-scan",
                cluster_name="narval",
                partition="gpubase_bygpu_b1",
                working_dir="/scratch/alice/clusterpilot_jobs/anisotropy-scan",
                status="OUT_OF_MEMORY",
                walltime="06:00:00",
                submitted_at=NOW - 260_000,
            ),
            NOW - 259_600, NOW - 251_000, False,
        ),
    ]


def demo_probe() -> ClusterProbe:
    """A GPU cluster with one MIG slice, so the GPU SIZE picker has content."""
    return ClusterProbe(
        cluster_name="narval",
        probed_at=NOW,
        partitions=[
            PartitionInfo("gpubase_bygpu_b1", "3:00:00", "gpu:a100:4", 141, False),
            PartitionInfo("gpubase_bygpu_b1", "3:00:00", "gpu:a100_3g.20gb:4", 141, False),
            PartitionInfo("cpubase_bycore_b1", "3:00:00", "", 20, True),
        ],
        julia_versions=["julia/1.11.3"],
        accounts=["def-alice"],
        account_max_wall={"def-alice": ""},
    )


def demo_availability() -> dict[str, PartitionAvailability]:
    return {
        "gpubase_bygpu_b1": PartitionAvailability(idle=12, mix=40, total=141, state="up"),
        "cpubase_bycore_b1": PartitionAvailability(idle=3, mix=9, total=20, state="up"),
    }


DESCRIPTION = (
    "Sweep temperature from 0.5 to 2.5 K over eight array tasks, one GPU each.\n"
    "Read the lattice from data/ladder.jld2 and write results into results/."
)

DEMO_SCRIPT = """#!/bin/bash
#SBATCH --job-name=ising-sweep
#SBATCH --account=def-alice
#SBATCH --array=0-7
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=6
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=%x-%A-%a.out

module load StdEnv/2023
module load julia/1.11.3
module load cuda/12.2

TEMPS=(0.50 0.75 1.00 1.25 1.50 1.75 2.00 2.50)
T=${TEMPS[$SLURM_ARRAY_TASK_ID]}

echo "Task $SLURM_ARRAY_TASK_ID: T = $T K"
julia --project=. scripts/driver.jl --temperature "$T" --out "results/T$T.jld2"
"""

DEMO_LOG = [
    ("#7a6a50", "── /scratch/alice/clusterpilot_jobs/ising-sweep/ising-sweep-4137812-0.out (array task 0; last 500 lines, [T] cycles tasks) ──"),
    ("#f0e8d0", "Task 0: T = 0.50 K"),
    ("#f0e8d0", "[ Info: CUDA device: NVIDIA A100-SXM4-40GB"),
    ("#f0e8d0", "[ Info: lattice 64x64x64, 4096 replicas"),
    ("#f0e8d0", "sweep  100000 / 500000   accept 0.412   E/N = -1.7431"),
    ("#f0e8d0", "sweep  200000 / 500000   accept 0.408   E/N = -1.7466"),
    ("#f0e8d0", "sweep  300000 / 500000   accept 0.405   E/N = -1.7482"),
    ("#6ed86e", "checkpoint written successfully: results/T0.5-chk3.jld2"),
]


@contextlib.contextmanager
def stubbed(db_path: Path) -> Iterator[None]:
    """Replace everything that would reach the network or the real machine."""
    daemon = MagicMock()
    daemon.run_forever = AsyncMock()
    with patch("clusterpilot.tui.app.PollDaemon", return_value=daemon), \
            patch("clusterpilot.tui.app.is_connected", return_value=True), \
            patch("clusterpilot.update.check_for_update", new=AsyncMock(return_value=None)), \
            patch(
                "clusterpilot.tui.submit.probe_cluster",
                new=AsyncMock(return_value=demo_probe()),
            ), \
            patch(
                "clusterpilot.tui.submit.fetch_availability",
                new=AsyncMock(return_value=demo_availability()),
            ), \
            patch(
                "clusterpilot.tui.config_view._CONTROL_PATH",
                "/home/alice/.ssh/cm_%h_%p_%r",
            ), \
            patch("clusterpilot.db.DB_PATH", db_path):
        yield


async def seed_database(db_path: Path) -> None:
    """Write the invented jobs into a throwaway database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await init_db(db)
        for job, started, finished, synced in demo_jobs():
            await insert_job(db, job)
            await db.execute(
                "UPDATE jobs SET started_at=?, finished_at=?, synced=? "
                "WHERE job_id=? AND cluster_name=?",
                (started, finished, int(synced), job.job_id, job.cluster_name),
            )
        await db.commit()


def pick_cluster(view: SubmitView) -> None:
    """Pick the DRAC-like cluster, which re-probes the partition list."""
    from textual.widgets import Select

    view.query_one("#cluster-select", Select).value = "narval"


def prime_submit_view(view: SubmitView) -> None:
    """Fill F2 as it looks just after a generation: description plus script."""
    from textual.widgets import Button, Select, Static, TextArea

    view.query_one("#partition-select", Select).value = "gpubase_bygpu_b1"
    view.query_one("#gpu-size-select", Select).value = "a100"
    view.query_one("#project-dir-input").value = "/home/alice/projects/spinglass"
    view.query_one("#script-path-input").value = "scripts/driver.jl"
    view.query_one("#extra-files-input").value = "data/ladder.jld2"
    view.query_one("#array-input").value = "0-7"
    view.query_one("#description-input", TextArea).load_text(DESCRIPTION)
    # The streaming path ends in exactly this pair of statements.
    view._generated_script = DEMO_SCRIPT
    view.query_one("#script-display", Static).update(_format_script(DEMO_SCRIPT))
    for btn_id in ("#btn-submit", "#btn-edit-script", "#btn-save", "#btn-clear"):
        view.query_one(btn_id, Button).disabled = False


def fill_log_pane(view: JobsView) -> None:
    """Put a plausible tail into the OUTPUT LOG pane."""
    from textual.widgets import RichLog

    widget = view.query_one("#log-display", RichLog)
    widget.clear()
    for colour, line in DEMO_LOG:
        widget.write(f"[{colour}]{line}[/]")


async def capture(db_path: Path) -> list[Path]:
    """Drive the app through F1, F2 and F9, saving one SVG per screen."""
    app = ClusterPilotApp(demo_config(), db_path=db_path)
    written: list[Path] = []
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with stubbed(db_path):
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()

            # F2 first: its partition probe needs a couple of event-loop turns
            # after the cluster is picked before the picker has any options.
            await pilot.press("f2")
            submit_view = app.query_one(SubmitView)
            for _ in range(4):
                await pilot.pause()
            pick_cluster(submit_view)
            for _ in range(4):
                await pilot.pause()
            prime_submit_view(submit_view)
            # The left column is taller than 36 rows: scroll it to the part the
            # README caption is about, the description and GENERATE SCRIPT.
            submit_view.query_one("#describe-panel").scroll_end(animate=False)
            submit_view.query_one("#description-input").focus()
            for _ in range(2):
                await pilot.pause()
            written.append(save(app, "tui-submit"))

            # Second F2 capture for the changelog: the pickers in view, with a
            # MIG slice chosen in GPU SIZE. The description scrolls off below.
            from textual.widgets import Select, Static
            submit_view.query_one("#gpu-size-select", Select).value = "a100_3g.20gb"
            slice_script = DEMO_SCRIPT.replace("--gres=gpu:a100:1", "--gres=gpu:a100_3g.20gb:1")
            submit_view._generated_script = slice_script
            submit_view.query_one("#script-display", Static).update(_format_script(slice_script))
            submit_view.query_one("#describe-panel").scroll_home(animate=False)
            submit_view.query_one("#gpu-size-select").focus()
            for _ in range(2):
                await pilot.pause()
            written.append(save(app, "tui-submit-gpu-size"))

            await pilot.press("f9")
            await pilot.pause()
            written.append(save(app, "tui-config"))

            await pilot.press("f1")
            await pilot.pause()
            jobs = app.query_one(JobsView)
            await jobs.select_job("4137812", "narval")
            fill_log_pane(jobs)
            await pilot.pause()
            written.append(save(app, "tui-jobs"))
    return written


def save(app: ClusterPilotApp, stem: str) -> Path:
    app.save_screenshot(f"{stem}.svg", path=str(OUT_DIR))
    target = OUT_DIR / f"{stem}.svg"
    print(f"wrote {target.relative_to(REPO_ROOT)}")
    return target


def to_png(svgs: list[Path], scale: int = 2) -> bool:
    """Render each SVG to a PNG beside it at *scale*, using vendored resvg."""
    if not RESVG.exists():
        print(f"resvg not found at {RESVG}; keeping the SVGs only", file=sys.stderr)
        return False
    script = """
const fs = require('fs');
const { Resvg } = require(process.argv[1]);
for (const file of JSON.parse(process.argv[2])) {
  const svg = new Resvg(fs.readFileSync(file), {
    fitTo: { mode: 'zoom', value: Number(process.argv[3]) },
    font: { loadSystemFonts: true, defaultFontFamily: 'Noto Sans Mono' },
  });
  const out = file.replace(/\\.svg$/, '.png');
  fs.writeFileSync(out, svg.render().asPng());
  console.log('wrote ' + out);
}
"""
    result = subprocess.run(
        ["node", "-e", script, str(RESVG), json.dumps([str(p) for p in svgs]), str(scale)],
        capture_output=True,
        text=True,
    )
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        print("PNG conversion failed; the SVGs are still current", file=sys.stderr)
        return False
    return True


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "screenshot-jobs.db"
        asyncio.run(seed_database(db_path))
        svgs = asyncio.run(capture(db_path))
    if "--no-png" in sys.argv:
        return 0
    return 0 if to_png(svgs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
