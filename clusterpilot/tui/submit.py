"""F2 SUBMIT view — describe job → AI generates script → upload + submit."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import aiosqlite
from rich.markup import escape
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.events import DescendantFocus
from textual.suggester import Suggester
from textual.widgets import Button, Input, Label, Select, Static, TextArea

from clusterpilot.cluster.probe import PartitionAvailability, fetch_availability, probe_cluster
from clusterpilot.cluster.slurm import SlurmError, submit
from clusterpilot.config import Config
from clusterpilot.db import DB_PATH, JobRecord, init_db, insert_job
from clusterpilot.jobs.ai_gen import ApiUsage, generate_script
from clusterpilot.jobs.env_detect import ScriptEnvironment, analyze_script
from clusterpilot.jobs.params_table import ParamsTableError, load_params_table
from clusterpilot.jobs.validate import (
    Finding,
    SubmitIntent,
    blocking,
    format_findings,
    validate_script,
)
from clusterpilot.jobs.preflight import PreflightError, warm_depot
from clusterpilot.jobs.sync import sync_job
from clusterpilot.ssh.connection import run_remote
from clusterpilot.ssh.rsync import read_ignore_file, upload, upload_file
from clusterpilot.tui.jobs import JobsView

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


class SubmitError(Exception):
    """Raised when the form cannot be turned into a submittable job."""


# Shown, and SUBMIT left disabled, when the model ran out of tokens mid-script.
# The remedy is the one that actually shortens the output: a long list of
# per-task parameters written into the script body is what usually pushes a
# generation over the ceiling, and a parameter table takes it out again.
_TRUNCATED_MESSAGE = (
    "Generation hit the token ceiling and was cut short. The script is "
    "incomplete and cannot be submitted. Shorten the description, or move the "
    "per-task parameters out of the script body and into a parameter table "
    "(the PARAM TABLE field) so the script only reads the row it needs."
)


# A job-name suffix ClusterPilot itself appends: "-MMDD-HHMM".
_JOB_NAME_SUFFIX_RE = re.compile(r"-\d{4}-\d{4}$")

# Cluster types whose scheduler routes the job itself, so the picked partition
# is a hint rather than a constraint, and whose compute nodes have no internet
# and need the login-node pre-flight. Trillium joined DRAC here in issue #29.
_ROUTED_TYPES: frozenset[str] = frozenset({"drac", "trillium"})


def _strip_job_name_suffix(job_name: str) -> str:
    """Remove a ClusterPilot "-MMDD-HHMM" suffix from a job name.

    Re-submitting the same description used to append a fresh timestamp to a
    name that already carried one, so a third run produced
    ``bench-0827-1431-0828-0902``. Stripping first means the suffix is always
    applied to the base name.
    """
    return _JOB_NAME_SUFFIX_RE.sub("", job_name)


def _local_results_root(project_dir_str: str) -> Path:
    """Directory that holds every job's local results.

    PROJECT DIR when it is set, the home directory otherwise. Never the working
    directory: results used to land wherever the TUI happened to be launched
    from, so the same job scattered its output across the filesystem and RSYNC
    could not find the previous run.
    """
    if project_dir_str:
        return Path(project_dir_str).expanduser() / "clusterpilot_jobs"
    return Path.home() / "clusterpilot_jobs"


def _normalise_driver_rel(project_dir: Path, raw: str) -> str:
    """Return the driver path as a project-relative posix path.

    ``rsync`` include patterns are matched against paths relative to the
    transfer root, so an absolute or ``./``-prefixed driver silently matched
    nothing and the job ran without its own script.

    Raises SubmitError when the path is absolute and outside PROJECT DIR:
    that file cannot travel with the project, so there is no path to write.
    """
    value = raw.strip()
    if not value:
        return ""

    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return Path(value).as_posix()

    root = project_dir.expanduser()
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raise SubmitError(
            f"DRIVER SCRIPT '{raw}' is outside PROJECT DIR ({root}). "
            f"Give a path relative to PROJECT DIR, or point PROJECT DIR at the "
            f"directory that contains the driver."
        ) from None


def _mkdir_command(remote_dirs: Iterable[str]) -> str:
    """One ``mkdir -p`` for every remote directory, or "" when there are none.

    One SSH round trip per extra file, each on the 30 s default timeout, is what
    made a batch of extra files time out on a busy login node.
    """
    unique = sorted({d for d in remote_dirs if d})
    if not unique:
        return ""
    return "mkdir -p " + " ".join(unique)


def _julia_upload_includes(project_dir: Path, driver_rel: str) -> list[str] | None:
    """Allowlist of paths to upload for a Julia project, or None.

    When *project_dir* contains a ``Project.toml`` the upload is reduced to the
    environment (Project/Manifest), the package source tree, and the driver
    script, preserving relative layout. Returns None for non-Julia projects, in
    which case the caller falls back to whole-tree blocklist upload.
    """
    if not (project_dir / "Project.toml").exists():
        return None
    includes = ["Project.toml", "Manifest.toml", "src/***"]
    if driver_rel and not driver_rel.startswith("src/"):
        includes.append(driver_rel)
    return includes


def _resolve_extra_file(entry: str, project_dir: Path) -> tuple[Path, Path, str | None]:
    """Resolve an EXTRA FILE entry to (local_path, remote_relative_path, warning).

    Relative entries land at their path under the job root. Absolute entries are
    relativised: inside PROJECT DIR they keep their project-relative path; outside
    PROJECT DIR they land at their basename in the job root (with a warning),
    instead of the old behaviour that reconstructed an absolute ``home/...`` tree
    on the remote.
    """
    p = Path(entry).expanduser()
    if p.is_absolute():
        resolved = p.resolve()
        try:
            rel = resolved.relative_to(project_dir.expanduser().resolve())
            return resolved, rel, None
        except ValueError:
            warning = (
                f"Extra file '{entry}' is outside PROJECT DIR; "
                f"placing it at the job root as '{resolved.name}'."
            )
            return resolved, Path(resolved.name), warning
    return project_dir / entry, Path(entry), None


def _read_julia_package_name(manifest: Path) -> str | None:
    """Return the ``name = "X"`` value from a Julia Project.toml, or None."""
    try:
        text = manifest.read_text()
    except OSError:
        return None
    match = re.search(r'^\s*name\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def _package_src_warning(project_dir: Path) -> str | None:
    """Warn when PROJECT DIR points inside a Julia package's ``src/``.

    CP uploads the *contents* of PROJECT DIR as the job root, so pointing it at a
    package's ``src/`` flattens the layout (the real root's Project.toml expects
    ``src/<Name>.jl``) and drops sibling dirs like ``scripts/``. PROJECT DIR
    should be the project root, i.e. the directory that holds Project.toml.
    """
    parent_manifest = project_dir.parent / "Project.toml"
    if not parent_manifest.exists():
        return None
    pkg_name = _read_julia_package_name(parent_manifest)
    is_package_src = (
        (pkg_name is not None and (project_dir / f"{pkg_name}.jl").exists())
        or project_dir.name == "src"
    )
    if not is_package_src:
        return None
    return (
        "PROJECT DIR looks like a Julia package's src/ directory. Set PROJECT DIR "
        "to the project root (the folder containing Project.toml) instead, or the "
        "package layout will break on the cluster."
    )


def _format_script(script: str) -> str:
    """Apply Rich colour markup to a SLURM script for display.

    Each line's text is escaped before the colour tags are applied, so literal
    square brackets in the script (bash array indices like ``${ARR[$i]}``,
    globs ``[abc]``, regex classes ``[0-9]``) are shown verbatim instead of
    being parsed as Rich markup and silently dropped.
    """
    out: list[str] = []
    for raw in script.splitlines():
        line = escape(raw)
        if raw.startswith("#SBATCH"):
            out.append(f"[bold #e8a020]{line}[/]")
        elif raw.startswith("#!") or (raw.startswith("#") and not raw.startswith("#SBATCH")):
            out.append(f"[#7a6a50]{line}[/]")
        elif raw.startswith("module"):
            out.append(f"[#50c8c8]{line}[/]")
        elif re.match(r"^(julia|python|bash|mpirun|srun)\b", raw):
            out.append(f"[#6ed86e]{line}[/]")
        elif raw == "":
            out.append("")
        else:
            out.append(f"[#f0e8d0]{line}[/]")
    return "\n".join(out)


def _extract(script: str, directive: str, default: str) -> str:
    for line in script.splitlines():
        if f"--{directive}=" in line:
            return line.split(f"--{directive}=")[-1].strip()
    return default


def _sanitise_script(script: str, job_name: str, is_array: bool = False) -> str:
    """Enforce correct SBATCH directives and strip absolute job-dir paths.

    The AI reliably deviates from prompt rules in two ways:

    1. ``--output`` — writes a full ``~/.../%x-%j.out`` path instead of the
       required bare ``%x-%j.out``.  SLURM does not expand ``~`` in
       ``#SBATCH`` directives (they are comments, not shell commands), so it
       treats the tilde as a literal character and creates a ``~`` subdirectory.

    2. Script body paths — writes ``~/clusterpilot_jobs/<job>/...`` which
       bash does not expand inside double quotes, producing doubled paths.

    ``--chdir`` is removed entirely.  SLURM defaults to using the submission
    directory as the working directory, and ``submit()`` already ``cd``s into
    the job directory before calling ``sbatch``.  A ``--chdir`` with ``~``
    would be treated as a relative path and create a literal ``~`` subdir.

    Every file reference in the script body should be a relative path (the
    CWD is the job directory).  This function enforces that deterministically.
    """
    tilde_dir    = f"~/clusterpilot_jobs/{job_name}"   # job dir, no trailing slash
    tilde_prefix = tilde_dir + "/"                      # job dir prefix with slash
    # Also catch $HOME-style paths the AI sometimes generates.
    home_dir     = f"$HOME/clusterpilot_jobs/{job_name}"
    home_prefix  = home_dir + "/"

    lines = []
    for line in script.splitlines():
        if re.match(r"^#SBATCH\s+--output=", line):
            # Relative path only. Array jobs get per-task logs via %A and %a.
            line = "#SBATCH --output=%x-%A-%a.out" if is_array else "#SBATCH --output=%x-%j.out"
        elif re.match(r"^#SBATCH\s+--chdir=", line):
            # Remove --chdir entirely.  The cd in submit() already sets
            # the correct CWD, and SLURM does not expand ~ in directives.
            continue
        elif re.match(r"^#SBATCH\s+-D\s", line):
            # -D is the short form of --chdir — also remove.
            continue
        elif not line.lstrip().startswith("#"):
            # Script body: strip the absolute job-directory prefix so all
            # paths become relative to the CWD (which IS the job dir).
            #   ~/clusterpilot_jobs/<job>/scripts/run.jl → scripts/run.jl
            #   ~/clusterpilot_jobs/<job>               → .  (e.g. --project=.)
            line = line.replace(tilde_prefix, "")
            line = line.replace(tilde_dir, ".")
            line = line.replace(home_prefix, "")
            line = line.replace(home_dir, ".")
        lines.append(line)
    return "\n".join(lines)


def _gres_gpu_type(gres: str) -> str:
    """The GPU type in a partition GRES, e.g. "a100" from "gpu:a100:4".

    Returns "" for a type-less or non-GPU GRES. A type containing "_" is a MIG
    slice ("a100_3g.20gb"); the probe lists each slice as its own partition row.
    """
    fields = gres.split(":")
    if len(fields) >= 3 and fields[0] == "gpu":
        return fields[1]
    return ""


def _sorted_gpu_types(types: Iterable[str]) -> list[str]:
    """Whole cards first, then MIG slices, each group alphabetical."""
    return sorted(set(types), key=lambda t: ("_" in t, t))


def _resolve_table_path(project_dir_str: str, table_raw: str) -> Path:
    """Resolve the PARAM TABLE field to a local path.

    An absolute path is taken as given. A relative one is resolved against
    PROJECT DIR when that field is filled in, and against the working
    directory otherwise.
    """
    table_path = Path(table_raw).expanduser()
    if table_path.is_absolute() or not project_dir_str:
        return table_path
    return Path(project_dir_str).expanduser() / table_path


@dataclass(frozen=True)
class GenerationCredential:
    """Which credential a generation will use, and where it is sent.

    ``ignored_env_var`` names the provider environment variable that is being
    bypassed in favour of the hosted proxy, "" when nothing is being bypassed.
    """

    api_key: str
    api_base_url: str
    hosted: bool = False
    ignored_env_var: str = ""


def _generation_credential(config: Config) -> GenerationCredential:
    """Pick the credential for AI script generation.

    Precedence is ``[defaults] api_key`` in config, then ``[hosted]
    api_token`` through the managed proxy, then the provider's environment
    variable. Only the config file counts as the user's own key at the second
    step: reading the effective key would let an exported ANTHROPIC_API_KEY
    silently take generation off a paid subscription and onto a personal key,
    with the dashboard still filling up from the separate sync path and
    nothing anywhere saying which credential paid. That is issue #25.
    """
    config_key = config.defaults.api_key
    env_key = config.env_api_key

    if config_key:
        return GenerationCredential(config_key, config.api_base_url)

    hosted = config.hosted
    if hosted.api_token and config.provider == "anthropic":
        return GenerationCredential(
            api_key=hosted.api_token,
            api_base_url=hosted.api_url.rstrip("/") + "/proxy",
            hosted=True,
            ignored_env_var=config.env_var_name if env_key else "",
        )

    return GenerationCredential(env_key, config.api_base_url)


class SubmitView(Static):
    """Left: description + partition picker + script path. Right: generated script."""

    # One warning per app run when an exported provider key is being ignored in
    # favour of the hosted proxy. A class attribute so a remount cannot reset
    # it: the point is to say it once, not once per visit to this screen.
    _env_key_warned: bool = False

    def compose(self) -> ComposeResult:
        with Vertical(id="submit-left"):
            with ScrollableContainer(id="describe-panel"):
                with Horizontal(id="cluster-row"):
                    yield Label("CLUSTER", classes="field-label")
                    yield Select(
                        [],
                        prompt="Select a cluster…",
                        id="cluster-select",
                    )

                with Horizontal(id="partition-row"):
                    yield Label("PARTITION", classes="field-label")
                    yield Select(
                        [],
                        prompt="Select a partition…",
                        id="partition-select",
                    )

                with Horizontal(id="gpu-row"):
                    yield Label("GPU SIZE", classes="field-label")
                    yield Select(
                        [],
                        allow_blank=True,
                        # Short enough not to wrap the row at 100 columns; the
                        # help line carries the rest.
                        prompt="(a whole GPU)",
                        id="gpu-size-select",
                    )

                with Horizontal(id="project-dir-row"):
                    yield Label("PROJECT DIR", classes="field-label")
                    yield Input(
                        placeholder="/path/to/project/  (optional; add .clusterpilotignore to exclude dirs)",
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

                with Horizontal(id="params-table-row"):
                    yield Label("PARAM TABLE", classes="field-label")
                    yield Input(
                        placeholder=(
                            "params.tsv or params.csv  (optional; one row per "
                            "array task, header names the variables)"
                        ),
                        id="params-table-input",
                    )

                with Horizontal(id="array-row"):
                    yield Label("ARRAY", classes="field-label")
                    yield Input(
                        placeholder="0-9  or  1-100%5  (optional — leave blank for a single job)",
                        id="array-input",
                    )

                yield Label("DESCRIBE YOUR JOB", id="describe-label")
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
                yield Button("SUBMIT", id="btn-submit", disabled=True)
                yield Button("EDIT", id="btn-edit-script", disabled=True)
                yield Button("SAVE", id="btn-save", disabled=True)
                yield Button("CLEAR", id="btn-clear", disabled=True)

    def on_mount(self) -> None:
        self._generated_script = ""
        self._findings: list[Finding] = []
        self._last_usage = ApiUsage()
        self._last_script_env: ScriptEnvironment | None = None
        # The job name as generated, without any "-MMDD-HHMM" uniqueness
        # suffix. Every submit derives its name from this, so re-submitting
        # cannot stack one suffix on top of another.
        self._base_job_name: str = ""
        self._partition_availability: dict[str, PartitionAvailability] = {}
        # GPU types the probe reports, per partition name and across the whole
        # cluster. The probe lists MIG instances as extra rows for the same
        # partition, so one partition can offer several types.
        self._gpu_types_by_partition: dict[str, list[str]] = {}
        self._all_gpu_types: list[str] = []
        self._init_done = False
        self._populate_cluster_select()
        # Probe immediately in case a ControlMaster socket is already open
        # from a prior session; fails silently if not connected.
        self._populate_partitions()

    def _populate_cluster_select(self) -> None:
        """Fill the cluster Select from the loaded config."""
        app = cast("ClusterPilotApp", self.app)
        clusters = app._config.clusters
        if not clusters:
            return
        select = self.query_one("#cluster-select", Select)
        options = [(c.name, c.name) for c in clusters]
        select.set_options(options)
        # Default to the first cluster.
        select.value = clusters[0].name

    def _selected_profile(self):
        """Return the ClusterProfile for the currently selected cluster."""
        app = cast("ClusterPilotApp", self.app)
        if not app._config.clusters:
            return None
        select = self.query_one("#cluster-select", Select)
        if select.value is not Select.NULL:
            profile = app._config.get_cluster(str(select.value))
            if profile is not None:
                return profile
        return app._config.clusters[0]

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
            if node_id == "partition-select":
                profile = self._selected_profile()
                if profile is not None and profile.cluster_type in _ROUTED_TYPES:
                    help_widget.update(_HELP_PARTITION_DRAC)
                else:
                    help_widget.update(_HELP_PARTITION)
                return
            if node_id in _HELP_MAP:
                help_widget.update(_HELP_MAP[node_id])
                return
        help_widget.update(_HELP_DEFAULT)

    # ── Cluster selection ──────────────────────────────────────────────────────

    @on(Select.Changed, "#cluster-select")
    def on_cluster_changed(self, event: Select.Changed) -> None:
        """Re-probe partitions whenever the user picks a different cluster."""
        if event.value is not Select.NULL:
            self._partition_availability = {}
            self.query_one("#partition-select", Select).set_options([])
            if self._init_done:
                # User-initiated change: connect if needed before probing.
                profile = self._selected_profile()
                if profile:
                    cast("ClusterPilotApp", self.app).ensure_connected(profile)
            else:
                # First event fires from the programmatic set in on_mount.
                self._init_done = True
            self._populate_partitions()

    # ── Partition selection ────────────────────────────────────────────────────

    @on(Select.Changed, "#partition-select")
    def on_partition_changed(self, event: Select.Changed) -> None:
        """Warn the user about partition state or saturation on selection."""
        # Select.NULL, not Select.BLANK, is the empty sentinel on Textual 8.x
        # (see #42): the GPU sizes must follow the picker either way.
        chosen = "" if event.value is Select.NULL else str(event.value)
        self._rebuild_gpu_sizes(chosen)
        if event.value is Select.NULL:
            return
        name = str(event.value)
        pa = self._partition_availability.get(name)
        if pa is None:
            return
        if pa.state == "down":
            self.app.notify(
                f"Partition '{name}' is DOWN ({pa.total} nodes) — "
                "job submission will be rejected.",
                severity="error",
                timeout=10,
            )
        elif pa.state in ("drain", "inact", "inactive"):
            self.app.notify(
                f"Partition '{name}' is draining ({pa.total} nodes) — "
                "no new jobs will start until it returns to service.",
                severity="warning",
                timeout=10,
            )
        elif pa.idle == 0 and pa.mix == 0:
            # On DRAC the picked partition is only a routing hint — the scheduler
            # places the job onto whatever partition matches at submit time, so
            # this partition's load is not predictive of queueing behaviour.
            profile = self._selected_profile()
            if profile is None or profile.cluster_type not in _ROUTED_TYPES:
                self.app.notify(
                    f"Partition '{name}' has no free nodes (0/{pa.total}) — "
                    "your job will queue until resources free up.",
                    severity="warning",
                    timeout=10,
                )

    # ── Partition probe ────────────────────────────────────────────────────────

    @work(thread=False, exclusive=True)
    async def _populate_partitions(self) -> None:
        """Probe the cluster and fill the partition Select widget."""
        profile = self._selected_profile()
        if profile is None:
            return
        select = self.query_one("#partition-select", Select)
        try:
            probe = await probe_cluster(profile.name, profile.host, profile.user)
        except Exception as exc:
            self.app.notify(f"Partition probe failed: {exc}", severity="warning", markup=False)
            return

        # Fetch live partition availability (not cached — always fresh).
        avail = await fetch_availability(profile.host, profile.user)
        self._partition_availability = avail

        # GPU partitions first (most ClusterPilot users need GPU), then CPU.
        ordered = probe.gpu_partitions() + probe.cpu_partitions()
        options: list[tuple[str, str]] = []
        for p in ordered:
            pa = avail.get(p.name)
            if pa is None:
                avail_str = ""
            elif pa.state in ("down", "drain", "inact", "inactive"):
                avail_str = f"  [{pa.state.upper()}  {pa.idle}/{pa.total} nodes]"
            elif pa.idle > 0:
                avail_str = f"  [{pa.idle}/{pa.total} free]"
            elif pa.mix > 0:
                avail_str = f"  [{pa.mix}/{pa.total} free (mix only)]"
            else:
                avail_str = f"  [0/{pa.total} free - queues]"

            if p.gres:
                label = f"{p.name}  (GPU: {p.gres}  max {p.max_time}){avail_str}"
            else:
                label = f"{p.name}  (CPU  max {p.max_time}){avail_str}"
            options.append((label, p.name))

        if options:
            select.set_options(options)
        else:
            self.app.notify("No partitions found — check cluster connection.", severity="warning")

        # GPU sizes come from the same probe: every gpu:<type>:<count> row,
        # whole cards and MIG slices alike (see _rebuild_gpu_sizes).
        by_partition: dict[str, list[str]] = {}
        for p in probe.gpu_partitions():
            gpu_type = _gres_gpu_type(p.gres)
            if gpu_type and gpu_type not in by_partition.setdefault(p.name, []):
                by_partition[p.name].append(gpu_type)
        self._gpu_types_by_partition = by_partition
        self._all_gpu_types = _sorted_gpu_types(
            {t for types in by_partition.values() for t in types}
        )
        self._rebuild_gpu_sizes(
            "" if select.value is Select.NULL else str(select.value)
        )

    def _rebuild_gpu_sizes(self, partition_name: str) -> None:
        """Refill the GPU SIZE picker for *partition_name*, "" meaning any.

        The row is hidden outright on a cluster whose probe reports no GPU
        partitions, so a CPU-only site never sees a field it cannot use.
        """
        row = self.query_one("#gpu-row")
        select = self.query_one("#gpu-size-select", Select)
        if not self._all_gpu_types:
            row.display = False
            return
        types = _sorted_gpu_types(self._gpu_types_by_partition.get(partition_name, []))
        if not types:
            # No partition picked, or one the probe has no GPU rows for: offer
            # every type the cluster has rather than an empty picker.
            types = self._all_gpu_types
        row.display = True
        select.set_options(
            [
                (f"{t}, slice" if "_" in t else f"{t}, whole GPU", t)
                for t in types
            ]
        )

    # ── Generate ──────────────────────────────────────────────────────────────

    @on(Button.Pressed, "#btn-generate")
    def on_generate(self) -> None:
        description = self.query_one("#description-input", TextArea).text.strip()
        if not description:
            self.app.notify("Enter a job description first.", severity="warning")
            return

        partition_select = self.query_one("#partition-select", Select)
        if partition_select.value is Select.NULL:
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
        profile = self._selected_profile()
        if profile is None:
            self.app.notify("No clusters configured.", severity="error")
            return

        # Hard partition constraint from picker.
        partition_select = self.query_one("#partition-select", Select)
        partition = (
            str(partition_select.value)
            if partition_select.value is not Select.NULL
            else ""
        )

        # GPU size from the picker: a whole card or a MIG slice. Blank leaves
        # the choice to the prompt's own default for this cluster type. The
        # empty sentinel is Select.NULL on Textual 8.x, not Select.NULL (#42).
        gpu_size_select = self.query_one("#gpu-size-select", Select)
        gpu_size = (
            "" if gpu_size_select.value is Select.NULL else str(gpu_size_select.value)
        )

        # Resolve driver script content for the AI.
        script_content: str | None = None
        driver_script: str | None = None
        project_dir_str = self.query_one("#project-dir-input", Input).value.strip()
        script_path_str = self.query_one("#script-path-input", Input).value.strip()

        if script_path_str:
            if project_dir_str:
                # Package mode: driver path is relative to the project root.
                # Absolute and "./"-prefixed paths break the upload filter, so
                # they are normalised here and rejected outright when they
                # cannot be expressed relative to PROJECT DIR.
                project_root_path = Path(project_dir_str).expanduser()
                try:
                    driver_script = _normalise_driver_rel(
                        project_root_path, script_path_str
                    )
                except SubmitError as exc:
                    self.app.notify(str(exc), severity="error", markup=False, timeout=15)
                    self.query_one("#btn-generate", Button).disabled = False
                    return
                if driver_script != script_path_str:
                    self.app.notify(
                        f"Driver script read as '{driver_script}', relative to "
                        f"PROJECT DIR.",
                        severity="warning",
                    )
                script_path_str = driver_script
                full_path = project_root_path / script_path_str
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
            src_warning = _package_src_warning(project_root)
            if src_warning:
                self.app.notify(src_warning, severity="warning", timeout=12)
            for candidate in ("Project.toml", "pyproject.toml", "requirements.txt"):
                manifest_path = project_root / candidate
                if manifest_path.exists():
                    manifest_content = f"# {candidate}\n{manifest_path.read_text()}"
                    manifest_name = candidate
                    break
            else:
                manifest_name = ""
        else:
            manifest_name = ""

        # Static analysis: detect language and third-party imports so the AI
        # can generate the correct environment setup steps. Also retained on
        # self so the SUBMIT handler can decide whether DRAC pre-flight is needed.
        script_env = analyze_script(
            script_content,
            driver_script or script_path_str or None,
            manifest_content,
            manifest_name=manifest_name,
        )
        self._last_script_env = script_env
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
            self.app.notify(f"Cluster probe failed: {exc}", severity="error", markup=False)
            self.query_one("#btn-generate", Button).disabled = False
            return

        provider = app._config.provider
        credential = _generation_credential(app._config)
        api_key = credential.api_key
        api_base_url = credential.api_base_url

        if credential.ignored_env_var and not self._env_key_warned:
            self._env_key_warned = True
            self.app.notify(
                f"{credential.ignored_env_var} is set but the hosted proxy is "
                f"being used; set api_key in config.toml to use your own key "
                f"instead.",
                severity="warning",
            )

        if not api_key and provider != "ollama":
            self.app.notify(
                f"No API key. Set api_key in config or "
                f"{app._config.env_var_name} env var.",
                severity="error",
            )
            self.query_one("#btn-generate", Button).disabled = False
            return

        script_widget = self.query_one("#script-display", Static)
        self._generated_script = ""
        self._last_usage = ApiUsage()

        extra_files_raw = self.query_one("#extra-files-input", Input).value.strip()
        extra_files = (
            [e.strip() for e in extra_files_raw.split(",") if e.strip()]
            if extra_files_raw else []
        )

        array_spec = self.query_one("#array-input", Input).value.strip()

        # A parameter table, when given, is the source of truth for the task
        # count. An explicit ARRAY field still wins, so an explicit subset of a
        # longer table stays runnable; the validator refuses a genuine mismatch.
        params_table = None
        self._params_table = None
        table_raw = self.query_one("#params-table-input", Input).value.strip()
        if table_raw:
            table_path = _resolve_table_path(project_dir_str, table_raw)
            try:
                params_table = load_params_table(table_path)
            except ParamsTableError as exc:
                self.app.notify(
                    f"Parameter table: {exc}",
                    severity="error", markup=False, timeout=12,
                )
                self.query_one("#btn-generate", Button).disabled = False
                return
            self._params_table = params_table
            if not array_spec:
                array_spec = params_table.array_spec
                self.app.notify(
                    f"Array set from the parameter table: {array_spec} "
                    f"({params_table.task_count} tasks)",
                    severity="information",
                )

        try:
            async for token in generate_script(
                description, probe, profile,
                model=app._config.model,
                api_key=api_key,
                provider=provider,
                api_base_url=api_base_url,
                partition=partition,
                gpu_size=gpu_size,
                array_spec=array_spec,
                script_content=script_content,
                driver_script=driver_script,
                manifest_content=manifest_content,
                extra_files=extra_files or None,
                script_env=script_env,
                fieldnotes_enabled=app._config.fieldnotes.enabled,
                params_table=params_table,
                usage=self._last_usage,
            ):
                self._generated_script += token
                script_widget.update(_format_script(self._generated_script))
        except Exception as exc:
            self.app.notify(f"Generation failed: {exc}", severity="error", markup=False)
            self.query_one("#btn-generate", Button).disabled = False
            return

        # Remember the base name this generation asked for, so a re-submit
        # timestamps the base rather than an already-timestamped name.
        self._base_job_name = _strip_job_name_suffix(
            _extract(self._generated_script, "job-name", "")
        )

        u = self._last_usage
        self.app.notify(
            f"Script generated — {u.input_tokens:,} in + {u.output_tokens:,} out "
            f"tokens (${u.cost_usd:.4f})",
            severity="information",
            timeout=8,
        )

        # A generation cut off at the token ceiling looks plausible and is
        # missing its tail. Refuse it outright: it must never reach sbatch.
        if self._last_usage.truncated:
            self.app.notify(
                _TRUNCATED_MESSAGE,
                severity="error", markup=False, timeout=20,
            )
            self.query_one("#btn-generate", Button).disabled = False
            self.query_one("#btn-submit", Button).disabled = True
            self.query_one("#btn-edit-script", Button).disabled = False
            self.query_one("#btn-save", Button).disabled = False
            self.query_one("#btn-clear", Button).disabled = False
            return

        # Check the generated script against what the user actually asked for,
        # BEFORE it can be submitted. Nothing else inspects the generation, so
        # this is the only gate between a plausible-looking script and sbatch.
        findings = validate_script(
            self._generated_script,
            intent=SubmitIntent(
                array_spec=array_spec,
                param_row_count=(
                    params_table.task_count if params_table is not None else None
                ),
                driver_rel=driver_script or "",
                upload_paths=tuple(extra_files),
                partition_name=partition or "",
                gpu_size=gpu_size,
                account=profile.account,
                cluster_type=profile.cluster_type,
            ),
            partitions=probe.partitions,
            account_max_wall=probe.account_max_wall,
        )
        self._findings = findings
        is_blocked = blocking(findings)
        if findings:
            self.app.notify(
                format_findings(findings),
                severity="error" if is_blocked else "warning",
                markup=False,
                timeout=20,
            )
        if is_blocked:
            self.app.notify(
                "SUBMIT is disabled: the generated script does not match what "
                "you asked for. Fix it with EDIT, or regenerate.",
                severity="error", markup=False, timeout=20,
            )

        self.query_one("#btn-generate", Button).disabled = False
        self.query_one("#btn-submit", Button).disabled = is_blocked
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
        profile = self._selected_profile()
        if profile is None:
            self.app.notify("No cluster selected.", severity="error")
            return

        # The script's own name wins (the user may have edited it), falling back
        # to the name this generation started from. Either way an existing
        # "-MMDD-HHMM" suffix is stripped before a new one can be added.
        base_job_name = _strip_job_name_suffix(
            _extract(script, "job-name", "")
            or self._base_job_name
            or f"cpjob_{int(time.time())}"
        )
        job_name  = base_job_name
        partition = _extract(script, "partition",  "skylake")
        walltime  = _extract(script, "time",       "01:00:00")
        account   = _extract(script, "account",    profile.account)

        project_dir_str = self.query_one("#project-dir-input", Input).value.strip()
        results_root = _local_results_root(project_dir_str)

        # Ensure unique job directory — append a short timestamp if a job
        # with this name already exists locally (repeat submissions with the
        # same description would otherwise overwrite the previous run's data).
        local_job_dir = results_root / job_name
        if local_job_dir.exists():
            suffix = time.strftime("%m%d-%H%M")
            job_name = f"{base_job_name}-{suffix}"
            # Rewrite --job-name in the script so SLURM log names match.
            script = re.sub(
                r"(#SBATCH\s+--job-name=)\S+",
                rf"\g<1>{job_name}",
                script,
            )

        remote_dir = profile.remote_job_dir(job_name)

        array_spec = self.query_one("#array-input", Input).value.strip()

        # Enforce correct SBATCH directives regardless of what the model wrote.
        script = _sanitise_script(script, job_name, is_array=bool(array_spec))
        self._generated_script = script   # keep TUI display in sync

        local_job_dir = results_root / job_name
        local_job_dir.mkdir(parents=True, exist_ok=True)

        script_name = f"{job_name}.sh"
        (local_job_dir / script_name).write_text(script)

        remote_script = f"{remote_dir}/{script_name}"

        self.app.notify(f"Uploading files to {remote_dir}…", severity="information")
        try:
            await run_remote(profile.host, profile.user, f"mkdir -p {remote_dir}")
        except Exception as exc:
            self.app.notify(f"Could not create remote directory: {exc}", severity="error", markup=False)
            self.query_one("#btn-submit", Button).disabled = False
            return

        try:
            if project_dir_str:
                # Package mode: rsync the project tree, then merge in the
                # generated .sh script from the staging dir.
                # Excludes = global defaults + .clusterpilotignore in the project root.
                project_dir = Path(project_dir_str).expanduser()
                excludes = list(app._config.defaults.upload_excludes)
                excludes += read_ignore_file(project_dir)

                # Julia-project allowlist: when a Project.toml is present, ship
                # only the environment (Project/Manifest), the package source,
                # and the driver — preserving layout — instead of the whole tree.
                try:
                    driver_rel = _normalise_driver_rel(
                        project_dir,
                        self.query_one("#script-path-input", Input).value,
                    )
                except SubmitError as exc:
                    self.app.notify(str(exc), severity="error", markup=False, timeout=15)
                    self.query_one("#btn-submit", Button).disabled = False
                    return
                includes = _julia_upload_includes(project_dir, driver_rel)

                # A Julia driver's include()d files are not imports, so the
                # allowlist never saw them and the job died on its first
                # include. Ship the ones that exist and say so for the rest.
                env = self._last_script_env
                if includes is not None and env is not None and env.included_files:
                    missing: list[str] = []
                    for rel_include in env.included_files:
                        if (project_dir / rel_include).exists():
                            if rel_include not in includes:
                                includes.append(rel_include)
                        else:
                            missing.append(rel_include)
                    if missing:
                        self.app.notify(
                            "Driver include()s files that do not exist locally, "
                            "so they cannot be uploaded: " + ", ".join(missing),
                            severity="warning", markup=False, timeout=12,
                        )

                await upload(
                    profile.host, profile.user,
                    project_dir, remote_dir,
                    excludes=excludes,
                    includes=includes,
                )
                await upload(profile.host, profile.user, local_job_dir, remote_dir)

                # The parameter table is data the script reads at run time, so
                # it must travel even though the Julia allowlist would drop it.
                table = getattr(self, "_params_table", None)
                if table is not None and table.path.exists():
                    await upload_file(
                        profile.host, profile.user, table.path, remote_dir,
                    )

                # Extra files: upload individually, bypassing ignore rules.
                # Every parent directory is created in ONE mkdir first: a
                # round trip per file on the default 30 s timeout is what made
                # a batch of extra files fail on a busy login node.
                extra_raw = self.query_one("#extra-files-input", Input).value.strip()
                if extra_raw:
                    planned: list[tuple[Path, str]] = []
                    for entry in (e.strip() for e in extra_raw.split(",") if e.strip()):
                        local_file, rel, warning = _resolve_extra_file(entry, project_dir)
                        if warning:
                            self.app.notify(warning, severity="warning")
                        if not local_file.exists():
                            self.app.notify(
                                f"Extra file not found, skipping: {entry}",
                                severity="warning",
                            )
                            continue
                        # Preserve subdirectory structure relative to the job root.
                        remote_file_dir = (
                            remote_dir if str(rel.parent) in (".", "")
                            else f"{remote_dir}/{rel.parent}"
                        )
                        planned.append((local_file, remote_file_dir))

                    mkdir_cmd = _mkdir_command(d for _, d in planned)
                    if mkdir_cmd:
                        await run_remote(
                            profile.host, profile.user, mkdir_cmd, timeout=120.0,
                        )
                    for local_file, remote_file_dir in planned:
                        await upload_file(
                            profile.host, profile.user,
                            local_file,
                            remote_file_dir,
                        )
            else:
                # Single-file mode: only the generated script is uploaded.
                await upload(profile.host, profile.user, local_job_dir, remote_dir)
        except Exception as exc:
            self.app.notify(f"Upload failed: {exc}", severity="error", markup=False)
            self.query_one("#btn-submit", Button).disabled = False
            return

        # ── DRAC pre-flight ───────────────────────────────────────────────────
        # DRAC compute nodes have no internet. Warm the package depot on the
        # login node now, against the rsynced project, so the compute-node
        # script can run offline. Skipped on Grex/generic where compute nodes
        # can reach pkg.julialang.org / PyPI directly.
        if profile.cluster_type in _ROUTED_TYPES and self._last_script_env is not None:
            self.app.notify(
                "Warming dependency cache on login node… first cold warm of a "
                "CUDA-heavy Manifest can take 15-25 min; subsequent runs against "
                "the same depot are sub-minute.",
                severity="information",
                timeout=1800,
            )
            try:
                ran = await warm_depot(
                    profile.host, profile.user, remote_dir,
                    self._last_script_env,
                    script=script,
                    cluster_type=profile.cluster_type,
                )
                if ran:
                    self.app.notify(
                        "✓ Dependency cache warmed on login node.",
                        severity="information",
                    )
            except PreflightError as exc:
                preflight_log = local_job_dir / "preflight.log"
                preflight_log.write_text(exc.stderr or str(exc))
                self.app.notify(
                    f"Pre-flight failed — full error written to {preflight_log}. "
                    "Submission aborted; open the file or run RSYNC after retry to debug.",
                    severity="error",
                    markup=False,
                    timeout=15,
                )
                self.query_one("#btn-submit", Button).disabled = False
                return

        self.app.notify("Submitting job…", severity="information")
        try:
            job_id = await submit(
                profile.host, profile.user, remote_script,
                working_dir=remote_dir,
            )
        except SlurmError as exc:
            self.app.notify(f"sbatch failed: {exc}", severity="error", markup=False)
            self.query_one("#btn-submit", Button).disabled = False
            return

        u = self._last_usage
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
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            model_used=u.model,
            array_spec=array_spec,
        )
        async with aiosqlite.connect(app._db_path) as db:
            await init_db(db)
            await insert_job(db, record)

        # Sync PENDING state immediately so the job appears in the dashboard.
        await sync_job(record, "PENDING", app._config.hosted)

        self.app.notify(
            f"✓ Job submitted! ID: {job_id}  →  switching to JOBS view",
            severity="information",
            timeout=8,
        )
        # Hand over to F1 on the job that was just submitted, and leave F2
        # ready for the next run of the same job: the script and its findings
        # go, everything the user typed stays.
        self._clear_generated_script()
        app.action_show_jobs()
        await app.query_one(JobsView).select_job(job_id, profile.name)

    def _clear_generated_script(self) -> None:
        """Drop the generated script and its validation findings.

        The form fields are deliberately untouched: after a submit, the next
        run of the same job should be one edit away.
        """
        self._generated_script = ""
        self._findings = []
        self.query_one("#script-display", Static).update(_EMPTY_HINT)
        for btn_id in ("#btn-submit", "#btn-edit-script", "#btn-save", "#btn-clear"):
            self.query_one(btn_id, Button).disabled = True

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
        downloads = Path.home() / "Downloads"
        base = downloads if downloads.is_dir() else Path.home()
        path = base / f"{job_name}.sh"
        path.write_text(self._generated_script)
        self.app.notify(f"Script saved to {path}", severity="information")

    @on(Button.Pressed, "#btn-clear")
    def on_clear(self) -> None:
        """Clear the description and the script. Every other field stays."""
        self.query_one("#description-input", TextArea).load_text("")
        self._clear_generated_script()


_EMPTY_HINT = (
    "[#3a3020]Describe your job on the left,\n"
    "then press \\[GENERATE SCRIPT].\n\n"
    "ClusterPilot will query:\n"
    "  sinfo        → available partitions\n"
    "  module avail → installed software\n"
    "  sacctmgr     → your account limits\n\n"
    "…and generate a correct SLURM\n"
    "script for this cluster.[/]"
)

_HELP_DEFAULT = "[#7a6a50]Tab into any field for contextual tips.[/]"

# Each help string is kept short enough to render in three lines at 60
# columns: #field-help has a fixed height so GENERATE never moves.
_HELP_CLUSTER = (
    "[#e8a020]CLUSTER[/]  [#7a6a50]Which cluster to submit to. The list comes "
    "from your config file; changing it re-probes the partitions.[/]"
)

_HELP_PARTITION = (
    "[#e8a020]PARTITION[/]  [#7a6a50]The SLURM partition for the job. GPU "
    "partitions are listed first; pick one your account can use.[/]"
)

_HELP_PARTITION_DRAC = (
    "[#e8a020]PARTITION[/]  [#7a6a50]On DRAC and Trillium the scheduler picks "
    "the partition itself. Your choice is only a hint for GPU type and "
    "walltime.[/]"
)

_HELP_GPU_SIZE = (
    "[#e8a020]GPU SIZE[/]  [#7a6a50]A whole card or a MIG slice. A slice queues "
    "sooner but cannot span devices. Blank means a whole GPU.[/]"
)

_HELP_PROJECT_DIR = (
    "[#e8a020]PROJECT DIR[/]  [#7a6a50]Optional local project root, rsynced to "
    "the cluster minus the built-in excludes and .clusterpilotignore.[/]"
)

_HELP_SCRIPT_PATH = (
    "[#e8a020]DRIVER SCRIPT[/]  [#7a6a50]The script the job runs. Relative to "
    "PROJECT DIR when that is set, otherwise an absolute path.[/]"
)

_HELP_EXTRA_FILES = (
    "[#e8a020]EXTRA FILES[/]  [#7a6a50]Comma-separated extra files to upload, "
    "bypassing the ignore rules. Paths are relative to PROJECT DIR.[/]"
)

_HELP_PARAMS_TABLE = (
    "[#e8a020]PARAM TABLE[/]  [#7a6a50]Optional .tsv or .csv, one row per array "
    "task, header naming the variables. It also sets the array size.[/]"
)

_HELP_ARRAY = (
    "[#e8a020]ARRAY[/]  [#7a6a50]Optional array spec, e.g. 0-9 or 1-100%5 (five "
    "at a time). Blank for a single job; a param table fills it in.[/]"
)

_HELP_DESCRIPTION = (
    "[#e8a020]DESCRIBE YOUR JOB[/]  [#7a6a50]What the job does, in plain "
    "English. The AI reads your driver script and manifest, then picks "
    "modules, GPU, memory and walltime.[/]"
)

_HELP_MAP: dict[str, str] = {
    "cluster-select":   _HELP_CLUSTER,
    "partition-select": _HELP_PARTITION,
    "gpu-size-select":  _HELP_GPU_SIZE,
    "project-dir-input": _HELP_PROJECT_DIR,
    "script-path-input": _HELP_SCRIPT_PATH,
    "extra-files-input": _HELP_EXTRA_FILES,
    "params-table-input": _HELP_PARAMS_TABLE,
    "array-input":      _HELP_ARRAY,
    "description-input": _HELP_DESCRIPTION,
}
