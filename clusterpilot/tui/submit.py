"""F2 SUBMIT view — describe job → AI generates script → upload + submit."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

import aiosqlite
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.events import DescendantFocus
from textual.suggester import Suggester
from textual.widgets import Button, Input, Label, Select, Static, TextArea

from clusterpilot.cluster.probe import probe_cluster
from clusterpilot.cluster.slurm import SlurmError, submit
from clusterpilot.db import DB_PATH, JobRecord, init_db, insert_job
from clusterpilot.jobs.ai_gen import generate_script
from clusterpilot.jobs.env_detect import analyze_script
from clusterpilot.ssh.connection import run_remote
from clusterpilot.ssh.rsync import read_ignore_file, upload, upload_file

if TYPE_CHECKING:
    from clusterpilot.tui.app import ClusterPilotApp
    from collections.abc import Callable


class PathSuggester(Suggester):
    """Inline filesystem path completer for Input widgets.

    When base_getter is provided, completions are relative paths within that
    base directory (used for DRIVER SCRIPT). Otherwise, absolute paths are
    completed (used for PROJECT DIR).

    dirs_only=True restricts completions to directories.
    """

    def __init__(
        self,
        *,
        dirs_only: bool = False,
        base_getter: "Callable[[], Path | None] | None" = None,
    ) -> None:
        super().__init__(use_cache=False, case_sensitive=True)
        self._dirs_only = dirs_only
        self._base_getter = base_getter

    async def get_suggestion(self, value: str) -> str | None:
        if not value:
            return None
        try:
            base = self._base_getter() if self._base_getter else None

            if base is not None:
                # Relative completion within base directory.
                full = base / value
                directory = full if value.endswith("/") else full.parent
                prefix = "" if value.endswith("/") else full.name
            else:
                # Absolute path completion.
                expanded = Path(value).expanduser()
                directory = expanded if value.endswith("/") else expanded.parent
                prefix = "" if value.endswith("/") else expanded.name

            if not directory.is_dir():
                return None

            matches = sorted(
                e for e in directory.iterdir()
                if e.name.startswith(prefix)
                and (not self._dirs_only or e.is_dir())
            )
            if not matches:
                return None

            entry = matches[0]
            suffix = "/" if entry.is_dir() else ""

            if base is not None:
                return str(entry.relative_to(base)) + suffix
            else:
                result = str(entry) + suffix
                # Preserve ~ prefix if the user typed it.
                if value.startswith("~"):
                    home = str(Path.home())
                    if result.startswith(home):
                        result = "~" + result[len(home):]
                return result

        except (PermissionError, ValueError, OSError):
            return None


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


def _sanitise_script(script: str, remote_dir: str, job_name: str) -> str:
    """Enforce correct SBATCH directives and strip absolute job-dir paths.

    The AI reliably deviates from two prompt rules:

    1. ``--output`` — writes a full ``~/.../%x-%j.out`` path instead of the
       required bare ``%x-%j.out``.  SLURM on Grex does not expand ``~`` in
       ``--output``, so it treats the path as relative to ``--chdir`` and
       creates a literal ``~`` subdirectory inside the job directory.

    2. Script body paths — writes ``"~/clusterpilot_jobs/<job>/..."`` inside
       double quotes.  Bash does not expand ``~`` inside double quotes, so
       Julia/Python receive the literal ``~`` string and resolve it relative
       to the CWD (which is already the job directory), producing a doubled
       path like ``<cwd>/~/clusterpilot_jobs/<job>/...``.

    Since ``--chdir`` sets the CWD to the job directory, every file reference
    in the script body can and should be a relative path.  This function
    enforces that deterministically, independent of what the model generates.
    """
    tilde_dir    = f"~/clusterpilot_jobs/{job_name}"   # job dir, no trailing slash
    tilde_prefix = tilde_dir + "/"                      # job dir prefix with slash

    lines = []
    for line in script.splitlines():
        if re.match(r"^#SBATCH\s+--output=", line):
            # Relative path only — SLURM expands %x and %j, not ~
            line = "#SBATCH --output=%x-%j.out"
        elif re.match(r"^#SBATCH\s+--chdir=", line):
            # Always use the authoritative remote_dir we computed
            line = f"#SBATCH --chdir={remote_dir}"
        elif not line.lstrip().startswith("#"):
            # Script body: strip the absolute job-directory prefix so all
            # paths become relative to --chdir.
            #   ~/clusterpilot_jobs/<job>/scripts/run.jl → scripts/run.jl
            #   ~/clusterpilot_jobs/<job>               → .  (e.g. --project=.)
            line = line.replace(tilde_prefix, "")
            line = line.replace(tilde_dir, ".")
        lines.append(line)
    return "\n".join(lines)


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

                with Horizontal(id="project-dir-row"):
                    yield Label("PROJECT DIR", classes="field-label")
                    yield Input(
                        placeholder="/path/to/project/  (optional — add .clusterpilot_ignore to exclude dirs)",
                        suggester=PathSuggester(dirs_only=True),
                        id="project-dir-input",
                    )

                with Horizontal(id="script-row"):
                    yield Label("DRIVER SCRIPT", classes="field-label")
                    yield Input(
                        placeholder="scripts/driver.jl  (relative to PROJECT DIR, or absolute path if no project dir)",
                        suggester=PathSuggester(base_getter=self._get_project_dir_path),
                        id="script-path-input",
                    )

                with Horizontal(id="extra-files-row"):
                    yield Label("EXTRA FILES", classes="field-label")
                    yield Input(
                        placeholder="data/ladder.jld2, data/config.toml  (comma-separated, relative to PROJECT DIR)",
                        suggester=PathSuggester(base_getter=self._get_project_dir_path),
                        id="extra-files-input",
                    )

                yield TextArea(
                    id="description-input",
                    language=None,
                )
                yield Static(_HELP_DEFAULT, id="field-help")
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
                yield Button("✎  EDIT", id="btn-edit-script", disabled=True)
                yield Button("⬇  SAVE", id="btn-save", disabled=True)
                yield Button("✕  CLEAR", id="btn-clear", disabled=True)

    def on_mount(self) -> None:
        self._generated_script = ""
        self._populate_partitions()

    def _get_project_dir_path(self) -> Path | None:
        """Return the resolved PROJECT DIR path, or None if unset/invalid."""
        val = self.query_one("#project-dir-input", Input).value.strip()
        if val:
            p = Path(val).expanduser()
            return p if p.is_dir() else None
        return None

    # ── Contextual help ───────────────────────────────────────────────────────

    def on_descendant_focus(self, event: DescendantFocus) -> None:
        """Update the help panel when any input field receives focus."""
        help_widget = self.query_one("#field-help", Static)
        # Walk up the DOM in case focus landed on an internal child widget
        # (e.g. Select's SelectCurrent, or TextArea's inner editor).
        for node in event.widget.ancestors_with_self:
            node_id = getattr(node, "id", None)
            if node_id in _HELP_MAP:
                help_widget.update(_HELP_MAP[node_id])
                return
        help_widget.update(_HELP_DEFAULT)

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

        # Resolve driver script content for the AI.
        script_content: str | None = None
        driver_script: str | None = None
        project_dir_str = self.query_one("#project-dir-input", Input).value.strip()
        script_path_str = self.query_one("#script-path-input", Input).value.strip()

        if script_path_str:
            if project_dir_str:
                # Package mode: driver path is relative to the project root.
                driver_script = script_path_str
                full_path = Path(project_dir_str).expanduser() / script_path_str
            else:
                # Single-file mode: treat as absolute/expandable path.
                full_path = Path(script_path_str).expanduser()

            if full_path.exists():
                script_content = full_path.read_text()
            else:
                self.app.notify(
                    f"Script file not found: {full_path}", severity="warning"
                )

        # When a project dir is set, read the dependency manifest so the AI
        # can infer runtime versions and packages without the user spelling them out.
        manifest_content: str | None = None
        if project_dir_str:
            project_root = Path(project_dir_str).expanduser()
            for candidate in ("Project.toml", "pyproject.toml", "requirements.txt"):
                manifest_path = project_root / candidate
                if manifest_path.exists():
                    manifest_content = f"# {candidate}\n{manifest_path.read_text()}"
                    break

        # Static analysis: detect language and third-party imports so the AI
        # can generate the correct environment setup steps.
        script_env = analyze_script(script_content, driver_script or script_path_str or None, manifest_content)
        if not script_env.has_manifest and script_env.third_party_imports:
            self.app.notify(
                f"No manifest found — inferred {len(script_env.third_party_imports)} "
                f"third-party package(s) from script imports. "
                f"Inline install will be added to the generated script.",
                severity="information",
                timeout=8,
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

        extra_files_raw = self.query_one("#extra-files-input", Input).value.strip()
        extra_files = (
            [e.strip() for e in extra_files_raw.split(",") if e.strip()]
            if extra_files_raw else []
        )

        try:
            async for token in generate_script(
                description, probe, profile,
                model=app._config.model,
                api_key=api_key,
                partition=partition,
                script_content=script_content,
                driver_script=driver_script,
                manifest_content=manifest_content,
                extra_files=extra_files or None,
                script_env=script_env,
            ):
                self._generated_script += token
                script_widget.update(_format_script(self._generated_script))
        except Exception as exc:
            self.app.notify(f"Generation failed: {exc}", severity="error")
            self.query_one("#btn-generate", Button).disabled = False
            return

        self.query_one("#btn-generate", Button).disabled = False
        self.query_one("#btn-submit", Button).disabled = False
        self.query_one("#btn-edit-script", Button).disabled = False
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

        remote_dir = profile.remote_job_dir(job_name)

        # Enforce correct SBATCH directives regardless of what the model wrote.
        script = _sanitise_script(script, remote_dir, job_name)
        self._generated_script = script   # keep TUI display in sync

        local_job_dir = Path.cwd() / "clusterpilot_jobs" / job_name
        local_job_dir.mkdir(parents=True, exist_ok=True)

        script_name = f"{job_name}.sh"
        (local_job_dir / script_name).write_text(script)

        remote_script = f"{remote_dir}/{script_name}"

        self.app.notify(f"Uploading files to {remote_dir}…", severity="information")
        try:
            await run_remote(profile.host, profile.user, f"mkdir -p {remote_dir}")
        except Exception as exc:
            self.app.notify(f"Could not create remote directory: {exc}", severity="error")
            self.query_one("#btn-submit", Button).disabled = False
            return

        project_dir_str = self.query_one("#project-dir-input", Input).value.strip()
        try:
            if project_dir_str:
                # Package mode: rsync the project tree, then merge in the
                # generated .sh script from the staging dir.
                # Excludes = global defaults + .clusterpilot_ignore in the project root.
                project_dir = Path(project_dir_str).expanduser()
                excludes = list(app._config.defaults.upload_excludes)
                excludes += read_ignore_file(project_dir)
                await upload(
                    profile.host, profile.user,
                    project_dir, remote_dir,
                    excludes=excludes,
                )
                await upload(profile.host, profile.user, local_job_dir, remote_dir)

                # Extra files: upload individually, bypassing ignore rules.
                extra_raw = self.query_one("#extra-files-input", Input).value.strip()
                if extra_raw:
                    for entry in (e.strip() for e in extra_raw.split(",") if e.strip()):
                        local_file = project_dir / entry
                        if not local_file.exists():
                            self.app.notify(
                                f"Extra file not found, skipping: {entry}",
                                severity="warning",
                            )
                            continue
                        # Preserve subdirectory structure relative to project root.
                        remote_file_dir = f"{remote_dir}/{Path(entry).parent}"
                        await run_remote(
                            profile.host, profile.user,
                            f"mkdir -p {remote_file_dir}",
                        )
                        await upload_file(
                            profile.host, profile.user,
                            local_file,
                            remote_file_dir,
                        )
            else:
                # Single-file mode: only the generated script is uploaded.
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

    # ── Edit script ───────────────────────────────────────────────────────────

    @on(Button.Pressed, "#btn-edit-script")
    def on_edit_script(self) -> None:
        if not self._generated_script:
            return
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
        job_name = _extract(self._generated_script, "job-name", "clusterpilot_job")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", prefix=f"{job_name}_", delete=False
        ) as f:
            f.write(self._generated_script)
            tmp_path = f.name
        try:
            with self.app.suspend():
                subprocess.run([editor, tmp_path])
            self._generated_script = Path(tmp_path).read_text()
            self.query_one("#script-display", Static).update(
                _format_script(self._generated_script)
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

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
        for btn_id in ("#btn-submit", "#btn-edit-script", "#btn-save", "#btn-clear"):
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

_HELP_DEFAULT = "[#7a6a50]Tab into any field for contextual tips.[/]"

_HELP_PARTITION = (
    "[#e8a020]PARTITION[/]  [#7a6a50]Select the SLURM partition for your job.\n"
    "GPU partitions are listed first — pick one your account has access to.\n"
    "If unsure, use your group's dedicated partition (e.g. stamps, lgpu).\n"
    "sbatch will return a clear error if you pick a partition you cannot use.[/]"
)

_HELP_PROJECT_DIR = (
    "[#e8a020]PROJECT DIR[/]  [#7a6a50]Optional. Local root of your project package.\n"
    "If set, the entire directory tree is rsynced to the cluster job directory,\n"
    "minus anything listed in [#f0e8d0].clusterpilot_ignore[/][#7a6a50] at the project root.\n"
    "Leave blank for self-contained single-script jobs.[/]"
)

_HELP_SCRIPT_PATH = (
    "[#e8a020]DRIVER SCRIPT[/]  [#7a6a50]The script the SLURM job will execute.\n"
    "With PROJECT DIR set: relative path within the project (e.g. scripts/run.jl).\n"
    "Without PROJECT DIR: absolute or ~/path to a self-contained script.\n"
    "The AI reads this file to infer modules, GPU count, and resource needs.[/]"
)

_HELP_EXTRA_FILES = (
    "[#e8a020]EXTRA FILES[/]  [#7a6a50]Comma-separated files to upload alongside the project,\n"
    "bypassing .clusterpilot_ignore. Use for per-job input data that normally\n"
    "lives in an excluded directory — e.g. a precomputed temperature ladder,\n"
    "a parameter file, or a checkpoint from a previous run.\n"
    "Paths are relative to PROJECT DIR. Leave blank if not needed.[/]"
)

_HELP_DESCRIPTION = (
    "[#e8a020]DESCRIBE YOUR JOB[/]  [#7a6a50]Tell the AI what this job does.\n"
    "Runtime and modules are inferred from your driver script and project manifest.\n"
    "Mention any of the following if known — the AI will make sensible defaults otherwise:\n"
    "  [#f0e8d0]Compute:[/][#7a6a50]   GPUs needed, or CPU core count\n"
    "  [#f0e8d0]Memory:[/][#7a6a50]    RAM per node if unusually large (e.g. 128G)\n"
    "  [#f0e8d0]Walltime:[/][#7a6a50]  estimated run time (e.g. 4 hours, overnight)\n"
    "  [#f0e8d0]I/O:[/][#7a6a50]       where to read inputs or write outputs[/]"
)

_HELP_MAP = {
    "partition-select": _HELP_PARTITION,
    "project-dir-input": _HELP_PROJECT_DIR,
    "script-path-input": _HELP_SCRIPT_PATH,
    "extra-files-input": _HELP_EXTRA_FILES,
    "description-input": _HELP_DESCRIPTION,
}
