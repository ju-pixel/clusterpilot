"""Regenerate the ClusterPilot demo clip from a stubbed app. Not a test.

Run it from the repository root with the project's virtualenv:

    .venv/bin/python tests/demo_video.py

It drives the same headless 120x36 TUI the README screenshots come from
(``tests/screenshots.py``, imported wholesale and never modified) through a
scripted ninety-second session, saving one SVG per step into a scratch
directory outside the repository, rendering each to a 2x PNG with the resvg
build vendored under ``frontend/node_modules``, inserting phosphor-amber title
cards, and assembling the lot with ffmpeg into

    docs/demo/clusterpilot-demo.mp4    H.264, yuv420p, 1080p-ish, 30 fps
    docs/demo/clusterpilot-demo.gif    palette-optimised, README size

Nothing here touches the network, the real config, the real job database or a
real cluster. Every name in shot is invented: the user is ``alice``, the
account ``def-alice``, the hosts ``login.example.ca`` and ``narval.example.ca``.

Flags:

    --frames-only   stop after the PNG frames, print the running time
    --no-gif        build the MP4 only

Set ``CLUSTERPILOT_DEMO_FRAMES`` to put the working frames somewhere specific.
Wherever they go, it is never inside the checkout.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import screenshots as shots  # noqa: E402  (the harness, reused, never edited)

from clusterpilot.jobs.validate import (  # noqa: E402
    SubmitIntent,
    format_findings,
    validate_script,
)
from clusterpilot.tui.app import ClusterPilotApp  # noqa: E402
from clusterpilot.tui.jobs import JobsView  # noqa: E402
from clusterpilot.tui.submit import SubmitView, _format_script  # noqa: E402

def _scratch_dir() -> Path:
    """Where the frames go. Never inside the repository.

    Eighty-odd 2x PNGs are working files, not project history, so they are
    written outside the checkout. ``CLUSTERPILOT_DEMO_FRAMES`` overrides the
    location; otherwise the session scratchpad is used when it exists, and the
    system temporary directory when it does not.
    """
    override = os.environ.get("CLUSTERPILOT_DEMO_FRAMES")
    if override:
        return Path(override).expanduser()
    session = Path(
        "/tmp/claude-1000/-home-juliafrank-repos-clusterpilot/"
        "83e0058f-9ce3-472d-8ea9-ab52aeaecffa/scratchpad"
    )
    base = session if session.is_dir() else Path(tempfile.gettempdir())
    return base / "demo-frames"


SCRATCH = _scratch_dir()
OUT_DIR = REPO_ROOT / "docs" / "demo"
MP4 = OUT_DIR / "clusterpilot-demo.mp4"
GIF = OUT_DIR / "clusterpilot-demo.gif"

SIZE = shots.SIZE           # (120, 36), the screenshot harness's terminal
SCALE = 2                   # resvg zoom, as the README screenshots use
FPS = 30                    # MP4 output rate
GIF_FPS = 12
GIF_WIDTHS = (960, 800)     # first that lands under the size budget wins
GIF_BUDGET = 8 * 1024 * 1024
MP4_HEIGHT = 1080           # width follows the 120x36 aspect, rounded even

CARD_BG = "#0c0a06"
CARD_FG = "#e8a020"
CARD_DIM = "#7a6a50"
CARD_FONT = "Noto Sans Mono"   # the face resvg already renders the TUI in

# The second array task the demo cycles to with [T], written the way
# ``JobsView._do_tail`` writes a real one.
DEMO_LOG_TASK1 = [
    ("#7a6a50", "── /scratch/alice/clusterpilot_jobs/ising-sweep/ising-sweep-4137812-1.out (array task 1; last 500 lines, [T] cycles tasks) ──"),
    ("#f0e8d0", "Task 1: T = 0.75 K"),
    ("#f0e8d0", "[ Info: CUDA device: NVIDIA A100-SXM4-40GB MIG 3g.20gb"),
    ("#f0e8d0", "[ Info: lattice 64x64x64, 4096 replicas"),
    ("#f0e8d0", "sweep  100000 / 500000   accept 0.437   E/N = -1.6902"),
    ("#f0e8d0", "sweep  200000 / 500000   accept 0.431   E/N = -1.6944"),
    ("#6ed86e", "checkpoint written successfully: results/T0.75-chk2.jld2"),
]

# The GPU size the demo picks, and the script that matches it.
GPU_SIZE = "a100_3g.20gb"
FINAL_SCRIPT = shots.DEMO_SCRIPT.replace(
    "--gres=gpu:a100:1", f"--gres=gpu:{GPU_SIZE}:1"
)
# The first generation asks for six hours on a partition that tops out at five,
# so the validator blocks it and SUBMIT stays disabled. The demo then shows the
# corrected script. Both are checked by the real validator, not staged.
DRAFT_SCRIPT = FINAL_SCRIPT.replace("--time=04:00:00", "--time=06:00:00")
PARTITION_MAX_TIME = "5:00:00"


def demo_probe_with_slices():
    """The screenshot probe, with a second MIG slice and a five-hour ceiling.

    Built by extending ``screenshots.demo_probe()`` rather than restating it,
    so the two stay in step: same cluster, same accounts, same partitions. Two
    changes are made for the clip. The extra ``a100_1g.5gb`` row gives the GPU
    SIZE picker both of the slices a real MIG A100 offers. The five-hour
    partition ceiling sits between the six hours the first generation asks for
    and the four hours the corrected one does, so the walltime check has
    something real to say in the one case and nothing in the other.
    """
    import dataclasses

    from clusterpilot.cluster.probe import PartitionInfo

    probe = shots.demo_probe()
    extra = PartitionInfo(
        "gpubase_bygpu_b1", PARTITION_MAX_TIME, "gpu:a100_1g.5gb:4", 141, False
    )
    partitions = [
        dataclasses.replace(p, max_time=PARTITION_MAX_TIME) for p in probe.partitions
    ]
    return dataclasses.replace(probe, partitions=[*partitions, extra])


def findings_for(script: str):
    """Run the real validator over *script* with the demo's own submit intent."""
    probe = demo_probe_with_slices()
    return validate_script(
        script,
        intent=SubmitIntent(
            array_spec="0-7",
            driver_rel="scripts/driver.jl",
            upload_paths=("scripts/driver.jl", "data/ladder.jld2"),
            partition_name="gpubase_bygpu_b1",
            gpu_size=GPU_SIZE,
            account="def-alice",
        ),
        partitions=probe.partitions,
        account_max_wall=probe.account_max_wall,
    )


# ── Frame book-keeping ────────────────────────────────────────────────────────

@dataclass
class Reel:
    """The ordered frames and how long each one stays on screen."""

    svgs: list[Path] = field(default_factory=list)
    seconds: list[float] = field(default_factory=list)
    # (index into svgs/seconds, card lines) for frames rendered as title cards
    # rather than captured from the app.
    cards: dict[int, tuple[str, ...]] = field(default_factory=dict)

    def _next(self) -> Path:
        return SCRATCH / f"frame{len(self.svgs):04d}.svg"

    def shot(self, app: ClusterPilotApp, hold: float) -> None:
        """Capture the app as it stands and hold it for *hold* seconds."""
        target = self._next()
        app.save_screenshot(target.name, path=str(SCRATCH))
        self.svgs.append(target)
        self.seconds.append(hold)

    def card(self, *lines: str, hold: float) -> None:
        """Insert a title card. The SVG is written once the geometry is known."""
        target = self._next()
        self.cards[len(self.svgs)] = lines
        self.svgs.append(target)
        self.seconds.append(hold)

    @property
    def total(self) -> float:
        return sum(self.seconds)


def write_cards(reel: Reel) -> None:
    """Render every deferred title card at the terminal frames' own geometry.

    The viewBox is read back off a captured frame rather than guessed, so a
    card and a screen are pixel-identical after resvg and ffmpeg's concat
    demuxer never sees two sizes.
    """
    sample = next(
        (p for i, p in enumerate(reel.svgs) if i not in reel.cards), None
    )
    if sample is None:
        raise RuntimeError("no captured frame to take the card geometry from")
    match = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', sample.read_text())
    if match is None:
        raise RuntimeError(f"no viewBox in {sample}")
    width, height = float(match.group(1)), float(match.group(2))

    for index, lines in reel.cards.items():
        reel.svgs[index].write_text(_card_svg(lines, width, height))


def _card_svg(lines: tuple[str, ...], width: float, height: float) -> str:
    """A dark card with amber monospace text, centred, in the TUI's palette."""
    sizes = [52.0] + [30.0] * (len(lines) - 1)
    colours = [CARD_FG] + [CARD_DIM] * (len(lines) - 1)
    gaps = [s * 1.9 for s in sizes]
    block = sum(gaps[1:])
    y = height / 2 - block / 2 + sizes[0] / 3

    body = []
    for text, size, colour, gap in zip(lines, sizes, colours, gaps):
        body.append(
            f'<text x="{width / 2:.1f}" y="{y:.1f}" fill="{colour}" '
            f'font-family="{CARD_FONT}, monospace" font-size="{size:.0f}" '
            f'text-anchor="middle">{_escape(text)}</text>'
        )
        y += gap
    return (
        f'<svg width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
        f'<rect width="{width}" height="{height}" fill="{CARD_BG}"/>'
        + "".join(body)
        + "</svg>"
    )


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── The scripted session ──────────────────────────────────────────────────────

async def record(db_path: Path) -> Reel:
    """Drive the TUI through the demo and return the reel of frames."""
    from textual.widgets import Button, Input, Select, Static, TextArea

    reel = Reel()
    app = ClusterPilotApp(shots.demo_config(), db_path=db_path)

    reel.card(
        "ClusterPilot",
        "Describe the job. Submit it. Watch it run.",
        hold=2.0,
    )

    # ``stubbed`` patches the probe to a cluster with one MIG slice; the demo
    # opens the GPU picker, so it wants both of the slices a real MIG A100
    # offers. The later patch wins over the one inside ``stubbed``.
    with shots.stubbed(db_path), patch(
        "clusterpilot.tui.submit.probe_cluster",
        new=AsyncMock(return_value=demo_probe_with_slices()),
    ):
        # notifications=True: Textual's test driver disables the toast rack by
        # default, and without it a notify() never reaches the screenshot.
        async with app.run_test(size=SIZE, notifications=True) as pilot:
            await pilot.pause()

            async def settle(turns: int = 2) -> None:
                for _ in range(turns):
                    await pilot.pause()

            # ── 2. Point it at your project ───────────────────────────────
            reel.card("Point it at your project.", hold=2.4)

            await pilot.press("f2")
            await settle(5)
            view = app.query_one(SubmitView)
            reel.shot(app, 2.0)

            view.query_one("#cluster-select", Select).value = "narval"
            view.query_one("#cluster-select").focus()
            await settle(5)
            reel.shot(app, 1.8)

            view.query_one("#partition-select", Select).value = "gpubase_bygpu_b1"
            view.query_one("#partition-select").focus()
            await settle(3)
            reel.shot(app, 1.8)

            # The GPU SIZE picker, open, so the whole card and the MIG slices
            # are visible side by side.
            gpu = view.query_one("#gpu-size-select", Select)
            gpu.focus()
            gpu.expanded = True
            await settle(3)
            reel.shot(app, 2.8)

            gpu.expanded = False
            gpu.value = GPU_SIZE
            await settle(3)
            reel.shot(app, 2.0)

            for widget_id, value, hold in (
                ("#project-dir-input", "/home/alice/projects/spinglass", 1.5),
                ("#script-path-input", "scripts/driver.jl", 1.5),
                ("#extra-files-input", "data/ladder.jld2", 1.5),
                ("#array-input", "0-7", 2.0),
            ):
                view.query_one(widget_id, Input).value = value
                view.query_one(widget_id).focus()
                await settle(2)
                reel.shot(app, hold)

            # ── 3. Say what the job does ──────────────────────────────────
            reel.card("Say what the job does.", hold=2.4)

            description = view.query_one("#description-input", TextArea)
            view.query_one("#describe-panel").scroll_end(animate=False)
            description.focus()
            await settle(2)
            reel.shot(app, 0.8)

            for cut in _typing_cuts(shots.DESCRIPTION):
                description.load_text(cut)
                view.query_one("#describe-panel").scroll_end(animate=False)
                await settle(1)
                reel.shot(app, 0.13)
            reel.seconds[-1] = 2.2

            # ── 4. Generate ───────────────────────────────────────────────
            reel.card("Generate.", hold=2.4)

            display = view.query_one("#script-display", Static)
            view.query_one("#btn-generate").focus()
            display.update("[#e8a020]Querying cluster and generating script…[/]")
            await settle(2)
            reel.shot(app, 1.6)

            for prefix in _script_prefixes(DRAFT_SCRIPT, steps=8):
                view._generated_script = prefix
                display.update(_format_script(prefix))
                await settle(1)
                reel.shot(app, 0.42)

            # Every generation is checked before it can be submitted, and this
            # first one asks for more walltime than the partition allows. The
            # findings come from the real validator, and SUBMIT stays disabled
            # exactly as ``_stream_script`` leaves it.
            for btn_id in ("#btn-edit-script", "#btn-save", "#btn-clear"):
                view.query_one(btn_id, Button).disabled = False
            draft_findings = findings_for(DRAFT_SCRIPT)
            if draft_findings:
                app.notify(
                    format_findings(draft_findings),
                    severity="error", markup=False, timeout=120,
                )
                app.notify(
                    "SUBMIT is disabled: the generated script does not match "
                    "what you asked for. Fix it with EDIT, or regenerate.",
                    severity="error", markup=False, timeout=120,
                )
            await settle(2)
            reel.shot(app, 5.0)

            # Regenerated, within the ceiling: the findings clear and SUBMIT
            # lights up.
            _clear_notifications(app)
            view._generated_script = FINAL_SCRIPT
            display.update(_format_script(FINAL_SCRIPT))
            for btn_id in ("#btn-submit", "#btn-edit-script", "#btn-save", "#btn-clear"):
                view.query_one(btn_id, Button).disabled = False
            view.query_one("#btn-submit").focus()
            await settle(3)
            reel.shot(app, 3.0)

            # ── 5. Submit ─────────────────────────────────────────────────
            reel.card("Submit.", hold=2.4)

            app.notify(
                "Uploading files to /scratch/alice/clusterpilot_jobs/ising-sweep…",
                severity="information",
                timeout=60,
            )
            await settle(2)
            reel.shot(app, 2.0)

            _clear_notifications(app)
            app.notify(
                "✓ Job submitted! ID: 4137812  →  switching to JOBS view",
                severity="information",
                timeout=60,
            )
            await settle(2)
            reel.shot(app, 2.4)
            _clear_notifications(app)

            # The three statements _do_submit ends with, run directly: the
            # upload, preflight and sbatch in between all need a real cluster.
            view._clear_generated_script()
            app.action_show_jobs()
            jobs = app.query_one(JobsView)
            await jobs.select_job("4137812", "narval")
            await settle(3)
            reel.shot(app, 3.0)

            # ── 6. Watch it run ───────────────────────────────────────────
            reel.card("Watch it run.", hold=2.4)

            reel.shot(app, 2.6)

            for step in range(1, len(shots.DEMO_LOG) + 1):
                _write_log(jobs, shots.DEMO_LOG[:step])
                await settle(1)
                reel.shot(app, 0.45)
            reel.seconds[-1] = 3.0

            await pilot.press("t")
            _write_log(jobs, DEMO_LOG_TASK1)
            await settle(2)
            reel.shot(app, 3.4)

            # ── 7. Nothing destructive without asking ─────────────────────
            reel.card("Nothing destructive without asking.", hold=2.4)

            await jobs.select_job("4136440", "grex")
            await settle(2)
            reel.shot(app, 2.0)

            await pilot.press("c")
            await settle(3)
            reel.shot(app, 4.0)

            await pilot.press("n")
            await settle(3)
            reel.shot(app, 1.6)

            # ── 8. Everything in one file ─────────────────────────────────
            reel.card("Everything in one file.", hold=2.4)

            await pilot.press("f9")
            await settle(3)
            reel.shot(app, 2.6)

            await pilot.press("pagedown")
            await settle(3)
            reel.shot(app, 3.2)

    reel.card("pip install clusterpilot", "clusterpilot.sh", hold=3.0)
    return reel


def _clear_notifications(app: ClusterPilotApp) -> None:
    """Drop any toast still on screen, so the next frame is clean."""
    clear = getattr(app, "clear_notifications", None)
    if clear is not None:
        clear()


def _write_log(jobs: JobsView, lines) -> None:
    """Refill the OUTPUT LOG pane, the way ``fill_log_pane`` does."""
    from textual.widgets import RichLog

    widget = jobs.query_one("#log-display", RichLog)
    widget.clear()
    for colour, line in lines:
        widget.write(f"[{colour}]{line}[/]")


def _typing_cuts(text: str, low: int = 3, high: int = 6) -> list[str]:
    """Growing prefixes of *text*, three to six characters at a time.

    The burst length cycles rather than being random, so two runs of this
    script produce the same frames.
    """
    cuts: list[str] = []
    pos = 0
    step = low
    while pos < len(text):
        pos = min(pos + step, len(text))
        cuts.append(text[:pos])
        step = low if step >= high else step + 1
    return cuts


def _script_prefixes(script: str, steps: int) -> list[str]:
    """*steps* growing line-prefixes of *script*, ending with the whole thing."""
    lines = script.splitlines()
    out: list[str] = []
    for step in range(1, steps + 1):
        take = max(1, round(len(lines) * step / steps))
        out.append("\n".join(lines[:take]))
    out[-1] = script
    return out


# ── Rendering and assembly ────────────────────────────────────────────────────

def png_size(path: Path) -> tuple[int, int]:
    """(width, height) straight out of a PNG's IHDR, no image library needed."""
    with path.open("rb") as handle:
        header = handle.read(24)
    return struct.unpack(">II", header[16:24])


def concat_list(reel: Reel, path: Path) -> None:
    """Write an ffmpeg concat list of PNGs with per-frame durations."""
    lines: list[str] = []
    for svg, seconds in zip(reel.svgs, reel.seconds):
        png = svg.with_suffix(".png")
        lines.append(f"file '{png}'")
        lines.append(f"duration {seconds:.3f}")
    # The concat demuxer ignores the final duration unless the last file is
    # repeated, which would otherwise clip the closing card to one frame.
    lines.append(f"file '{reel.svgs[-1].with_suffix('.png')}'")
    path.write_text("\n".join(lines) + "\n")


def run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr[-4000:])
        raise SystemExit(f"command failed: {args[0]}")


def build_mp4(list_file: Path) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-vf", f"fps={FPS},scale=-2:{MP4_HEIGHT}:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "slow", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(MP4),
    ])


def build_gif(list_file: Path, work: Path) -> int:
    """Build the GIF at the widest size that fits the budget. Returns it."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for width in GIF_WIDTHS:
        palette = work / f"palette-{width}.png"
        # format=rgb24 is load-bearing, not tidying. resvg writes RGBA PNGs,
        # and with an alpha channel still present the GIF encoder cannot do
        # its transparency-based frame differencing: every frame is stored in
        # full and this ninety-second clip comes out at 60 MB rather than one
        # and a bit. Dropping alpha first is the whole difference.
        scale = f"fps={GIF_FPS},scale={width}:-2:flags=lanczos,format=rgb24"
        run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-vf", f"{scale},palettegen=stats_mode=diff", str(palette),
        ])
        run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-i", str(palette),
            "-lavfi",
            # dither=none: the TUI is flat blocks of colour, and a dither
            # would only sprinkle noise across them and cost compression.
            f"{scale}[x];[x][1:v]paletteuse=dither=none:diff_mode=rectangle",
            "-loop", "0", str(GIF),
        ])
        size = GIF.stat().st_size
        print(f"gif at {width}px: {size / 1e6:.2f} MB")
        if size <= GIF_BUDGET or width == GIF_WIDTHS[-1]:
            return width
    return GIF_WIDTHS[-1]


def main() -> int:
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "demo-jobs.db"
        asyncio.run(shots.seed_database(db_path))
        reel = asyncio.run(record(db_path))

    write_cards(reel)
    print(f"{len(reel.svgs)} frames, {reel.total:.1f} s of screen time")

    if not shots.to_png(reel.svgs, scale=SCALE):
        return 1

    sizes = {png_size(p.with_suffix(".png")) for p in reel.svgs}
    if len(sizes) != 1:
        raise SystemExit(f"frames are not all one size: {sorted(sizes)}")
    width, height = sizes.pop()
    print(f"frame size {width}x{height}")

    if "--frames-only" in sys.argv:
        return 0

    list_file = SCRATCH / "frames.txt"
    concat_list(reel, list_file)
    build_mp4(list_file)
    print(f"wrote {MP4.relative_to(REPO_ROOT)} ({MP4.stat().st_size / 1e6:.2f} MB)")

    if "--no-gif" not in sys.argv:
        gif_width = build_gif(list_file, SCRATCH)
        print(
            f"wrote {GIF.relative_to(REPO_ROOT)} "
            f"({GIF.stat().st_size / 1e6:.2f} MB, {gif_width}px wide)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
