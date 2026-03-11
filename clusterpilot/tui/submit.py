"""F2 SUBMIT view — describe job → AI generates script → upload + submit."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

import aiosqlite
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, Input, Label, Select, Static, TextArea

from clusterpilot.cluster.probe import probe_cluster
from clusterpilot.cluster.slurm import SlurmError, submit
from clusterpilot.db import DB_PATH, JobRecord, init_db, insert_job
from clusterpilot.jobs.ai_gen import generate_script
from clusterpilot.ssh.rsync import upload

if TYPE_CHECKING:
    from clusterpilot.tui.app import ClusterPilotApp


def _format_script(script: str) -> str:
    """Apply Rich colour markup to a SLURM script for display."""
    out: list[str] = []
    for line in script.splitlines():
        if line.startswith("#SBATCH"):
            out.append(f"[bold #e8a020]{line}[/]")
        elif line.startswith("#!") or (line.startswith("#") and not line.startswith("#SBATCH")):
            out.append(f"[#7a6a50]{line}[/]")
        elif line.startswith("module"):
            out.append(f"[#50c8c8]{line}[/]")
        elif re.match(r"^(julia|python|bash|mpirun|srun)\b", line):
            out.append(f"[#6ed86e]{line}[/]")
        elif line == "":
            out.append("")
        else:
            out.append(f"[#f0e8d0]{line}[/]")
    return "\n".join(out)


def _extract(script: str, directive: str, default: str) -> str:
    for line in script.splitlines():
        if f"--{directive}=" in line:
            return line.split(f"--{directive}=")[-1].strip()
    return default


class SubmitView(Static):
    """Left: description + partition picker + script path. Right: generated script."""

    def compose(self) -> ComposeResult:
        with Vertical(id="submit-left"):
            with Vertical(id="describe-panel"):
                yield Label("═ DESCRIBE YOUR JOB ", id="describe-title")

                with Horizontal(id="partition-row"):
                    yield Label("PARTITION", classes="field-label")
                    yield Select(
                        [],
                        prompt="Probing cluster…",
                        id="partition-select",
                    )

                with Horizontal(id="script-row"):
                    yield Label("SCRIPT", classes="field-label")
                    yield Input(
                        placeholder="/path/to/your/script.jl  (optional — helps AI pick resources)",
                        id="script-path-input",
                    )

                yield TextArea(
                    id="description-input",
                    language=None,
                )
                with Horizontal(id="generate-row"):
                    yield Button(
                        "⚙  GENERATE SCRIPT",
                        id="btn-generate",
                        disabled=False,
                    )

        with Vertical(id="submit-right"):
            with Vertical(id="script-panel"):
                yield Label("═ GENERATED SLURM SCRIPT ", id="script-title")
                with ScrollableContainer(id="script-scroll"):
                    yield Static(_EMPTY_HINT, id="script-display")

            with Horizontal(id="submit-actions"):
                yield Button(
                    "⚡  UPLOAD + SUBMIT",
                    id="btn-submit",
                    disabled=True,
                )
                yield Button("⬇  SAVE", id="btn-save", disabled=True)
                yield Button("✕  CLEAR", id="btn-clear", disabled=True)

    def on_mount(self) -> None:
        self._generated_script = ""
        self._populate_partitions()

    # ── Partition probe ────────────────────────────────────────────────────────

    @work(thread=False, exclusive=True)
    async def _populate_partitions(self) -> None:
        """Probe the cluster and fill the partition Select widget."""
        app = cast("ClusterPilotApp", self.app)
        if not app._config.clusters:
            return
        profile = app._config.clusters[0]
        select = self.query_one("#partition-select", Select)
        try:
            probe = await probe_cluster(profile.name, profile.host, profile.user)
        except Exception as exc:
            self.app.notify(f"Partition probe failed: {exc}", severity="warning")
            return

        # GPU partitions first (most ClusterPilot users need GPU), then CPU.
        ordered = probe.gpu_partitions() + probe.cpu_partitions()
        options: list[tuple[str, str]] = []
        for p in ordered:
            if p.gres:
                label = f"{p.name}  (GPU: {p.gres}  max {p.max_time})"
            else:
                label = f"{p.name}  (CPU  max {p.max_time})"
            options.append((label, p.name))

        if options:
            select.set_options(options)
        else:
            self.app.notify("No partitions found — check cluster connection.", severity="warning")

    # ── Generate ──────────────────────────────────────────────────────────────

    @on(Button.Pressed, "#btn-generate")
    def on_generate(self) -> None:
        description = self.query_one("#description-input", TextArea).text.strip()
        if not description:
            self.app.notify("Enter a job description first.", severity="warning")
            return

        partition_select = self.query_one("#partition-select", Select)
        if partition_select.value is Select.BLANK:
            self.app.notify(
                "No partition selected — the AI will choose one from the available list.",
                severity="warning",
                timeout=5,
            )

        self.query_one("#btn-generate", Button).disabled = True
        self.query_one("#script-display", Static).update(
            "[#e8a020]Querying cluster and generating script…[/]"
        )
        self._stream_script(description)

    @work(thread=False, exclusive=True)
    async def _stream_script(self, description: str) -> None:
        app = cast("ClusterPilotApp", self.app)
        if not app._config.clusters:
            self.app.notify("No clusters configured.", severity="error")
            return

        profile = app._config.clusters[0]

        # Hard partition constraint from picker.
        partition_select = self.query_one("#partition-select", Select)
        partition = (
            str(partition_select.value)
            if partition_select.value is not Select.BLANK
            else ""
        )

        # Read script file content so the AI can inspect it.
        script_content: str | None = None
        script_path_str = self.query_one("#script-path-input", Input).value.strip()
        if script_path_str:
            script_path = Path(script_path_str).expanduser()
            if script_path.exists():
                script_content = script_path.read_text()
            else:
                self.app.notify(
                    f"Script file not found: {script_path}", severity="warning"
                )

        # Load or refresh cluster probe (returns cache if < 24h old).
        try:
            probe = await probe_cluster(profile.name, profile.host, profile.user)
        except Exception as exc:
            self.app.notify(f"Cluster probe failed: {exc}", severity="error")
            self.query_one("#btn-generate", Button).disabled = False
            return

        api_key = app._config.api_key
        if not api_key:
            self.app.notify(
                "No API key. Set api_key in config or ANTHROPIC_API_KEY env var.",
                severity="error",
            )
            self.query_one("#btn-generate", Button).disabled = False
            return

        script_widget = self.query_one("#script-display", Static)
        self._generated_script = ""

        try:
            async for token in generate_script(
                description, probe, profile,
                model=app._config.model,
                api_key=api_key,
                partition=partition,
                script_content=script_content,
            ):
                self._generated_script += token
                script_widget.update(_format_script(self._generated_script))
        except Exception as exc:
            self.app.notify(f"Generation failed: {exc}", severity="error")
            self.query_one("#btn-generate", Button).disabled = False
            return

        self.query_one("#btn-generate", Button).disabled = False
        self.query_one("#btn-submit", Button).disabled = False
        self.query_one("#btn-save", Button).disabled = False
        self.query_one("#btn-clear", Button).disabled = False

    # ── Submit ────────────────────────────────────────────────────────────────

    @on(Button.Pressed, "#btn-submit")
    def on_submit(self) -> None:
        if not self._generated_script:
            return
        self.query_one("#btn-submit", Button).disabled = True
        self._do_submit()

    @work(thread=False, exclusive=True)
    async def _do_submit(self) -> None:
        app = cast("ClusterPilotApp", self.app)
        script = self._generated_script
        profile = app._config.clusters[0]

        job_name  = _extract(script, "job-name",  f"cpjob_{int(time.time())}")
        partition = _extract(script, "partition",  "skylake")
        walltime  = _extract(script, "time",       "01:00:00")
        account   = _extract(script, "account",    profile.account)

        local_job_dir = Path.cwd() / "clusterpilot_jobs" / job_name
        local_job_dir.mkdir(parents=True, exist_ok=True)

        script_name = f"{job_name}.sh"
        (local_job_dir / script_name).write_text(script)

        remote_dir    = profile.remote_job_dir(job_name)
        remote_script = f"{remote_dir}/{script_name}"

        self.app.notify(f"Uploading files to {remote_dir}…", severity="information")
        try:
            await upload(profile.host, profile.user, local_job_dir, remote_dir)
        except Exception as exc:
            self.app.notify(f"Upload failed: {exc}", severity="error")
            self.query_one("#btn-submit", Button).disabled = False
            return

        self.app.notify("Submitting job…", severity="information")
        try:
            job_id = await submit(
                profile.host, profile.user, remote_script,
                working_dir=remote_dir,
            )
        except SlurmError as exc:
            self.app.notify(f"sbatch failed: {exc}", severity="error")
            self.query_one("#btn-submit", Button).disabled = False
            return

        record = JobRecord(
            job_id=job_id,
            job_name=job_name,
            cluster_name=profile.name,
            host=profile.host,
            user=profile.user,
            account=account,
            partition=partition,
            script_path=remote_script,
            working_dir=remote_dir,
            local_dir=str(local_job_dir),
            walltime=walltime,
        )
        async with aiosqlite.connect(app._db_path) as db:
            await init_db(db)
            await insert_job(db, record)

        self.app.notify(
            f"✓ Job submitted! ID: {job_id}  →  switching to JOBS view",
            severity="information",
            timeout=8,
        )
        app.action_show_jobs()

    # ── Save / Clear ──────────────────────────────────────────────────────────

    @on(Button.Pressed, "#btn-save")
    def on_save(self) -> None:
        if not self._generated_script:
            return
        job_name = _extract(self._generated_script, "job-name", "clusterpilot_job")
        path = Path.cwd() / f"{job_name}.sh"
        path.write_text(self._generated_script)
        self.app.notify(f"Script saved to {path}", severity="information")

    @on(Button.Pressed, "#btn-clear")
    def on_clear(self) -> None:
        self._generated_script = ""
        self.query_one("#description-input", TextArea).load_text("")
        self.query_one("#script-display", Static).update(_EMPTY_HINT)
        for btn_id in ("#btn-submit", "#btn-save", "#btn-clear"):
            self.query_one(btn_id, Button).disabled = True


_EMPTY_HINT = (
    "[#3a3020]Describe your job on the left,\n"
    "then press [GENERATE SCRIPT].\n\n"
    "ClusterPilot will query:\n"
    "  sinfo        → available partitions\n"
    "  module avail → installed software\n"
    "  sacctmgr     → your account limits\n\n"
    "…and generate a correct SLURM\n"
    "script for this cluster.[/]"
)
