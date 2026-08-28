"""ClusterPilot Textual application."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiosqlite
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.events import DescendantFocus
from textual.widgets import Input, Static, TabbedContent, TabPane

from clusterpilot import __version__
from clusterpilot.config import Config
from clusterpilot.db import DB_PATH, get_total_usage, init_db
from clusterpilot.jobs.ai_gen import _PRICING
from clusterpilot.jobs.daemon import PollDaemon
from clusterpilot.config import ClusterProfile
from clusterpilot.ssh.connection import is_connected, open_connection
from clusterpilot.tui.config_view import ConfigView
from clusterpilot.tui.jobs import JobsView
from clusterpilot.tui.submit import SubmitView
from clusterpilot.tui.widgets.confirm import ConfirmScreen
from clusterpilot.tui.widgets.file_explorer import FileExplorer, save_recent_path

log = logging.getLogger(__name__)


class TitleBar(Static):
    def __init__(self, config: Config) -> None:
        self._config = config
        self._cost_text = ""
        super().__init__(self._build_content())

    def _cluster_indicator(self, c: "ClusterProfile") -> str:
        if is_connected(c.host, c.user):
            return f"[#6ed86e]●[/] {c.name}"
        return f"[#3a3020]●[/] [#7a6a50]{c.name}[/]"

    def _build_content(self) -> str:
        clusters = "  ".join(self._cluster_indicator(c) for c in self._config.clusters)
        cost = f"  [#3d3520]│[/]  {self._cost_text}" if self._cost_text else ""
        return (
            f"[bold #e8a020]◈ CLUSTERPILOT[/]  [#7a6a50]v{__version__}[/]  "
            f"[#3d3520]│[/]  {clusters}{cost}"
        )

    def refresh_status(self) -> None:
        """Re-render with current SSH connection state for each cluster."""
        self.update(self._build_content())

    def set_cost(self, cost_usd: float) -> None:
        self._cost_text = f"[#7a6a50]API spend:[/] [#e8a020]${cost_usd:.4f}[/]"
        self.update(self._build_content())


class StatusBar(Static):
    DEFAULT_TEXT = (
        "[bold #e8a020]F1[/][#7a6a50] JOBS  [/]"
        "[bold #e8a020]F2[/][#7a6a50] SUBMIT  [/]"
        "[bold #e8a020]F3[/][#7a6a50] FILES  [/]"
        "[bold #e8a020]F9[/][#7a6a50] CONFIG  [/]"
        "[bold #e8a020]Q[/][#7a6a50] QUIT  [/]"
        "[bold #e8a020]↑↓[/][#7a6a50] SELECT[/]"
    )

    def __init__(self) -> None:
        super().__init__(self.DEFAULT_TEXT)


HINT_DEFAULT = "Tab moves between fields.  F1 jobs  F2 submit  F3 files  F9 config  Q quit"

# One line per focusable control, keyed by widget id. Anything the user can
# tab to on F1, F2 or F9 belongs here: the hint bar is the only always-visible
# explanation of what the focused control does.
HINTS: dict[str, str] = {
    # F1 JOBS
    "job-list":           "Up and down pick a job. The bracketed letters act on the selected one.",
    "btn-rsync":          "Download this job's results and logs to your machine.",
    "btn-kill":           "Cancel this job on the cluster with scancel. Asks first.",
    "btn-tail":           "Show the last 500 log lines, refreshing while the job runs.",
    "btn-log":            "Fetch the whole log for the selected job.",
    "btn-clean":          "Delete the job's working directory on the cluster. Local results are kept.",
    "btn-delete":         "Forget this job from the local history. Nothing on the cluster is touched.",
    "log-display":        "Output log. PageUp and PageDown scroll it.",
    # F2 SUBMIT
    "cluster-select":     "Choose which configured cluster the job goes to.",
    "partition-select":   "Choose the partition. Left blank, the AI picks one from the probed list.",
    "gpu-size-select":    "Whole GPU or a MIG slice. Blank asks for a whole GPU of the partition's type.",
    "project-dir-input":  "Local project root to upload. Blank for a self-contained single script.",
    "script-path-input":  "The script the job runs, relative to the project directory.",
    "extra-files-input":  "Extra files to upload, comma-separated, bypassing the exclude rules.",
    "params-table-input": "A .tsv or .csv of per-task parameters, one row per array task.",
    "array-input":        "SLURM array spec, e.g. 0-9 or 1-100%5. Blank for a single job.",
    "description-input":  "Describe the job in plain English, then press GENERATE SCRIPT.",
    "btn-generate":       "Ask the AI for a SLURM script for this cluster and driver.",
    "btn-submit":         "Upload the project and submit the script with sbatch.",
    "btn-edit-script":    "Open the generated script in your editor before submitting.",
    "btn-save":           "Save the generated script to a file.",
    "btn-clear":          "Clear the description and the generated script.",
    "script-scroll":      "The generated script. PageUp and PageDown scroll it.",
    # F9 CONFIG
    "config-scroll":      "Your loaded configuration. PageUp and PageDown scroll it.",
    "btn-edit-config":    "Open config.toml in your editor, then reload it.",
    # Confirmation modal
    "btn-confirm":        "Go ahead with the action described above. The y key does the same.",
    "btn-cancel":         "Leave everything as it is. Escape or n does the same.",
}


class HintBar(Static):
    """One-line explanation of whatever currently has focus."""

    def __init__(self) -> None:
        super().__init__(HINT_DEFAULT)

    def show_hint(self, text: str) -> None:
        self.update(text)


class ClusterPilotApp(App):
    """ClusterPilot terminal UI — amber phosphor edition."""

    TITLE = "ClusterPilot"
    SUB_TITLE = "AI-assisted HPC workflow"

    BINDINGS = [
        Binding("f1", "show_jobs", "Jobs", show=False),
        Binding("f2", "show_submit", "Submit", show=False),
        Binding("f3", "toggle_explorer", "Files", show=False),
        Binding("f9", "show_config", "Config", show=False),
        Binding("q", "confirm_quit", "Quit", show=False),
    ]

    CSS = """
$bg:        #0c0a06;
$bg2:       #111008;
$bg3:       #171410;
$amber:     #e8a020;
$amberDim:  #7a5010;
$amberLo:   #3a2808;
$green:     #6ed86e;
$greenDim:  #2a5a2a;
$red:       #e05050;
$redDim:    #5a1a1a;
$cyan:      #50c8c8;
$white:     #f0e8d0;
$dim:       #7a6a50;
$dimmer:    #3a3020;
$border:    #2a2415;
$border2:   #3d3520;

Screen {
    background: $bg;
    color: $white;
}

TitleBar {
    dock: top;
    height: 1;
    background: $bg3;
    color: $amber;
    padding: 0 1;
}

StatusBar {
    dock: bottom;
    height: 1;
    background: $amberLo;
    color: $amberDim;
    padding: 0 1;
}

/* margin-bottom lifts it clear of the status bar: Textual docks every
   bottom-docked widget onto the same edge, so they would otherwise overlap. */
HintBar {
    dock: bottom;
    height: 1;
    margin-bottom: 1;
    background: $bg3;
    color: $dim;
    padding: 0 1;
}

TabbedContent {
    height: 1fr;
    background: $bg;
}

TabbedContent > Tabs {
    background: $bg2;
    border-bottom: solid $border;
}

Tab {
    color: $dim;
    background: transparent;
}

Tab.-active {
    color: $amber;
    background: $bg3;
    text-style: bold;
}

Tab:hover {
    color: $white;
    background: $bg3;
}

/* ── Jobs view ──────────────────────────── */
JobsView {
    layout: horizontal;
    background: $bg;
    padding: 1;
}

#queue-panel {
    width: 34;
    height: 1fr;
    border: solid $amberDim;
    background: $bg;
}

#queue-title {
    background: $bg3;
    color: $amber;
    text-style: bold;
    width: 1fr;
    padding: 0 1;
}

#job-list {
    height: 1fr;
    background: $bg;
    scrollbar-color: $amberDim;
}

ListView > ListItem {
    background: $bg;
    padding: 0;
}

ListView > ListItem.--highlight {
    background: $amberLo;
}

#detail-col {
    width: 1fr;
    height: 1fr;
    layout: vertical;
    padding-left: 1;
}

#meta-panel {
    height: auto;
    max-height: 10;
    border: solid $amberDim;
    background: $bg;
    padding: 0 1;
}

#meta-title {
    color: $amber;
    text-style: bold;
    background: $bg3;
    padding: 0 1;
    width: 1fr;
}

#meta-content {
    color: $white;
    padding: 0 1;
    height: auto;
}

#log-panel {
    height: 1fr;
    margin-top: 1;
    border: solid $amberDim;
    background: $bg;
}

#log-title {
    color: $amber;
    text-style: bold;
    background: $bg3;
    padding: 0 1;
    width: 1fr;
}

#log-display {
    height: 1fr;
    background: $bg;
    scrollbar-color: $amberDim;
    padding: 0 1;
}

/* Six action buttons on two rows of three, so the bar never clips: at the
   detail column's width (about 60 columns on a 100-column terminal) six
   buttons side by side do not fit. */
#action-bar {
    height: 6;
    margin-top: 1;
    layout: grid;
    grid-size: 3;
    grid-rows: 3;
    grid-gutter: 0 1;
}

#action-bar Button {
    width: 1fr;
    min-width: 12;
    margin: 0;
}

/* ── Submit view ────────────────────────── */
SubmitView {
    layout: horizontal;
    background: $bg;
    padding: 1;
}

#submit-left {
    width: 1fr;
    height: 1fr;
    layout: vertical;
    padding-right: 1;
}

#describe-panel {
    border: solid $amberDim;
    background: $bg;
    height: 1fr;
    padding: 0 1;
    scrollbar-color: $amberDim;
}

#cluster-row {
    height: auto;
    margin-bottom: 0;
    layout: horizontal;
}

#cluster-select {
    width: 1fr;
    background: $bg3;
    border: solid $border2;
    color: $white;
}

#cluster-select:focus {
    border: solid $amberDim;
}

#partition-row {
    height: auto;
    margin-bottom: 0;
    layout: horizontal;
}

#partition-select {
    width: 1fr;
    background: $bg3;
    border: solid $border2;
    color: $white;
}

#partition-select:focus {
    border: solid $amberDim;
}

/* Shown only once a probe reports GPU partitions (tui/submit.py). */
#gpu-row {
    display: none;
    height: auto;
    margin-bottom: 0;
    layout: horizontal;
}

#gpu-size-select {
    width: 1fr;
    background: $bg3;
    border: solid $border2;
    color: $white;
}

#gpu-size-select:focus {
    border: solid $amberDim;
}

#project-dir-row {
    height: auto;
    margin-bottom: 0;
    layout: horizontal;
}

#script-row {
    height: auto;
    margin-bottom: 0;
    layout: horizontal;
}

#extra-files-row {
    height: auto;
    margin-bottom: 0;
    layout: horizontal;
}

#params-table-row {
    height: auto;
    margin-bottom: 0;
    layout: horizontal;
}

#params-table-input {
    width: 1fr;
    background: $bg3;
    border: solid $border2;
    color: $white;
}

#params-table-input:focus {
    border: solid $amberDim;
}

#array-row {
    height: auto;
    margin-bottom: 0;
    layout: horizontal;
}

#extra-files-input {
    width: 1fr;
    background: $bg3;
    border: solid $border2;
    color: $white;
}

#extra-files-input:focus {
    border: solid $amberDim;
}

#array-input {
    width: 1fr;
    background: $bg3;
    border: solid $border2;
    color: $white;
}

#array-input:focus {
    border: solid $amberDim;
}

.field-label {
    width: 14;
    color: $dim;
    text-style: bold;
    height: 3;
    content-align: left middle;
}

Select > SelectCurrent {
    background: $bg3;
    color: $white;
}

SelectOverlay {
    background: $bg2;
    border: solid $amberDim;
}

SelectOverlay > OptionList {
    background: $bg2;
    color: $white;
}

SelectOverlay > OptionList > .option-list--option-highlighted {
    background: $amberLo;
    color: $amber;
}

#project-dir-input {
    width: 1fr;
    background: $bg3;
    border: solid $border2;
    color: $white;
}

#project-dir-input:focus {
    border: solid $amberDim;
}

#script-path-input {
    width: 1fr;
    background: $bg3;
    border: solid $border2;
    color: $white;
}

#script-path-input:focus {
    border: solid $amberDim;
}

/* Fixed height: the help text changes with focus, and an auto height moved
   the GENERATE button every time it did. */
#field-help {
    height: 3;
    margin-top: 0;
    margin-bottom: 1;
    padding: 0 1;
    color: $dim;
    background: $bg;
}

#describe-label {
    color: $amber;
    text-style: bold;
    margin-top: 1;
    margin-bottom: 0;
    padding: 0 1;
}

#description-input {
    border: solid $border2;
    background: $bg3;
    color: $white;
    height: 8;
    margin-top: 0;
    scrollbar-color: $amberDim;
}

#description-input:focus {
    border: solid $amberDim;
}

#generate-row {
    height: 3;
    margin-top: 1;
    margin-bottom: 1;
    layout: horizontal;
    align: right middle;
}

#btn-generate {
    background: $amberLo;
    color: $amber;
    border: solid $amberDim;
    text-style: bold;
}

#btn-generate:hover { background: $amberDim; }
#btn-generate:disabled { background: $dimmer; color: $dim; }

#submit-right {
    width: 1fr;
    height: 1fr;
    layout: vertical;
}

#script-panel {
    border: solid $greenDim;
    background: $bg;
    height: 1fr;
}

#script-title {
    color: $green;
    text-style: bold;
    background: $bg3;
    padding: 0 1;
    width: 1fr;
}

#script-scroll {
    height: 1fr;
    background: $bg;
    scrollbar-color: $amberDim;
    padding: 0 1;
}

#script-display {
    color: $white;
    background: $bg;
}

/* Two rows of two, like #action-bar on F1, so the four buttons fit inside
   the script pane at 100 columns instead of clipping to SUBMIT alone (#40). */
#submit-actions {
    height: 6;
    margin-top: 1;
    layout: grid;
    grid-size: 2;
    grid-rows: 3;
    grid-gutter: 0 1;
}

#btn-submit,
#btn-edit-script,
#btn-save,
#btn-clear {
    width: 1fr;
    min-width: 12;
    margin: 0;
}

#btn-submit {
    background: $greenDim;
    color: $green;
    border: solid $green;
    text-style: bold;
}

#btn-submit:hover { background: $green; color: $bg; }
#btn-submit:disabled { background: $dimmer; color: $dim; border: solid $dimmer; }

/* ── Config view ────────────────────────── */
ConfigView {
    layout: vertical;
    background: $bg;
    padding: 1;
    height: 1fr;
}

/* Focusable so the keyboard can scroll it; the EDIT button is docked out of
   the scroll flow so it is always reachable. */
#config-scroll {
    height: 1fr;
    background: $bg;
    scrollbar-color: $amberDim;
}

#config-content {
    height: auto;
}

#config-actions {
    dock: bottom;
    height: 3;
    margin-top: 1;
    layout: horizontal;
}

/* ── File explorer sidebar ──────────────── */
FileExplorer {
    dock: left;
    width: 34;
    height: 1fr;
    background: $bg2;
    border-right: solid $border;
    display: none;
    layout: vertical;
}

FileExplorer.-visible {
    display: block;
}

#explorer-title {
    background: $bg3;
    color: $amber;
    text-style: bold;
    width: 1fr;
    padding: 0 1;
    height: 1;
}

#explorer-path-input {
    background: $bg3;
    border: solid $border2;
    color: $white;
    height: 3;
}

#explorer-path-input:focus {
    border: solid $amberDim;
}

#explorer-tree {
    height: 1fr;
    background: $bg2;
    scrollbar-color: $amberDim;
    color: $white;
}

DirectoryTree > .tree--guides {
    color: $dimmer;
}

DirectoryTree > .tree--guides-hover {
    color: $amberDim;
}

DirectoryTree > .tree--guides-selected {
    color: $amber;
}

DirectoryTree .directory--folder-icon {
    color: $amber;
}

DirectoryTree .--highlight {
    background: $amberLo;
    color: $amber;
}

/* ── Confirmation modal ─────────────────── */
ConfirmScreen {
    align: center middle;
    background: $bg 70%;
}

#confirm-panel {
    width: 60;
    max-width: 100%;
    height: auto;
    border: solid $amber;
    background: $bg2;
    padding: 1 2;
}

#confirm-title {
    color: $amber;
    text-style: bold;
    width: 1fr;
    margin-bottom: 1;
}

#confirm-body {
    color: $white;
    height: auto;
    margin-bottom: 1;
}

#confirm-actions {
    height: 3;
    align: right middle;
}

#btn-confirm {
    color: $red;
    border: solid $redDim;
}

#btn-confirm:hover {
    background: $redDim;
}

/* ── Shared ─────────────────────────────── */
Button {
    background: $bg3;
    color: $amber;
    border: solid $amberDim;
    margin-right: 1;
}

Button:hover { background: $amberLo; }
#btn-clean { color: $red; border: solid $redDim; }
#btn-clean:hover { background: $redDim; }
#btn-clean:disabled { color: $dim; border: solid $dimmer; background: $bg3; }
"""

    def __init__(self, config: Config, db_path: Path = DB_PATH) -> None:
        super().__init__()
        self._config = config
        self._db_path = db_path
        self._daemon_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield TitleBar(self._config)
        yield FileExplorer(id="file-explorer")
        with TabbedContent(initial="jobs"):
            with TabPane("  F1  JOBS  ", id="jobs"):
                yield JobsView()
            with TabPane("  F2  SUBMIT  ", id="submit"):
                yield SubmitView()
            with TabPane("  F9  CONFIG  ", id="config"):
                yield ConfigView()
        # Docked bottom in this order: the status bar sits on the last row,
        # the hint bar on the row above it.
        yield StatusBar()
        yield HintBar()

    async def on_mount(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await init_db(db)
        self.query_one(TitleBar).refresh_status()
        self._start_daemon()
        await self._refresh_cost()
        self.set_interval(30, self._refresh_cost)
        self._check_for_update()

    async def _refresh_cost(self) -> None:
        """Update the title bar with cumulative API spend."""
        async with aiosqlite.connect(self._db_path) as db:
            await init_db(db)
            inp, out = await get_total_usage(db)
        # Use default sonnet pricing for the aggregate (good enough for display).
        inp_rate, out_rate = _PRICING.get(self._config.model, (3.00, 15.00))
        cost = (inp * inp_rate + out * out_rate) / 1_000_000
        self.query_one(TitleBar).set_cost(cost)

    @work(thread=False)
    async def _check_for_update(self) -> None:
        """Check PyPI for a newer release and notify the user if one exists."""
        from clusterpilot.update import check_for_update
        latest = await check_for_update()
        if latest:
            self.notify(
                f"ClusterPilot {latest} is available — "
                "run: pip install --upgrade clusterpilot",
                title="Update available",
                severity="information",
                timeout=15,
            )

    def ensure_connected(self, profile: "ClusterProfile") -> bool:
        """Ensure a ControlMaster socket is open for *profile*.

        Suspends the TUI and prompts for interactive auth if not already
        connected. Returns True if connected after this call, False if the
        attempt failed. Safe to call from both sync and async contexts.
        """
        if is_connected(profile.host, profile.user):
            return True
        self.notify(
            f"Opening SSH connection to {profile.host} — "
            "authenticate in the terminal below…",
            severity="information",
            timeout=30,
        )
        try:
            with self.suspend():
                open_connection(profile.host, profile.user)
            self.notify(f"Connected to {profile.host}", severity="information")
            self.query_one(TitleBar).refresh_status()
            return True
        except Exception as exc:
            self.notify(
                f"SSH failed ({profile.host}): {exc}",
                severity="error",
                timeout=20,
                markup=False,
            )
            return False

    def _start_daemon(self) -> None:
        daemon = PollDaemon(self._config, self._db_path)
        self._daemon_task = asyncio.get_event_loop().create_task(
            daemon.run_forever()
        )
        log.debug("Poll daemon started")

    async def on_unmount(self) -> None:
        if self._daemon_task:
            self._daemon_task.cancel()

    # ── Hint bar ──────────────────────────────────────────────────────────────

    def on_descendant_focus(self, event: DescendantFocus) -> None:
        """Show the hint for whatever just took focus."""
        try:
            hint_bar = self.query_one(HintBar)
        except NoMatches:
            return
        # Walk up in case focus landed on an internal child (Select's
        # SelectCurrent, for instance) rather than the widget we know by id.
        for node in event.widget.ancestors_with_self:
            node_id = getattr(node, "id", None)
            if node_id in HINTS:
                hint_bar.show_hint(HINTS[node_id])
                return
        hint_bar.show_hint(HINT_DEFAULT)

    # ── Quit ──────────────────────────────────────────────────────────────────

    def action_confirm_quit(self) -> None:
        """Quit, but confirm first when jobs are still running."""
        try:
            running = self.query_one(JobsView).running_jobs()
        except NoMatches:
            running = []
        if not running:
            self.exit()
            return
        listed = ", ".join(f"{j.job_name} (#{j.job_id})" for j in running[:3])
        if len(running) > 3:
            listed += f", and {len(running) - 3} more"
        body = (
            f"{len(running)} job(s) are still running on the cluster: {listed}. "
            "Quitting stops monitoring and notifications; the jobs keep running "
            "and ClusterPilot picks them up again next time it starts."
        )
        self.push_screen(ConfirmScreen("QUIT CLUSTERPILOT", body), self._quit_confirmed)

    def _quit_confirmed(self, confirmed: bool | None) -> None:
        if confirmed:
            self.exit()

    # ── Tab navigation ────────────────────────────────────────────────────────

    def action_show_jobs(self) -> None:
        self.query_one(TabbedContent).active = "jobs"
        # Put focus inside JobsView so its single-letter action keys work
        # straight away rather than only after the user tabs into the pane.
        self.query_one(JobsView).focus_job_list()

    def action_show_submit(self) -> None:
        self.query_one(TabbedContent).active = "submit"
        self._focus("#cluster-select")

    def action_show_config(self) -> None:
        self.query_one(TabbedContent).active = "config"
        self._focus("#config-scroll")

    def _focus(self, selector: str) -> None:
        """Focus the first control on a screen, so the hint bar follows it."""
        try:
            self.query_one(selector).focus()
        except NoMatches:
            pass

    def action_toggle_explorer(self) -> None:
        explorer = self.query_one(FileExplorer)
        explorer.toggle_class("-visible")

    # ── File explorer events ───────────────────────────────────────────────────

    def on_file_explorer_file_selected(
        self, event: FileExplorer.FileSelected
    ) -> None:
        """Wire file clicks to the F2 Submit form when that tab is active."""
        if self.query_one(TabbedContent).active != "submit":
            # On other tabs: just show the path in a notification.
            self.notify(str(event.path), title="File", timeout=4)
            return

        submit = self.query_one(SubmitView)
        proj_input = submit.query_one("#project-dir-input", Input)
        script_input = submit.query_one("#script-path-input", Input)

        proj_val = proj_input.value.strip()
        script_val = script_input.value.strip()

        if not proj_val:
            # Nothing set yet — fill PROJECT DIR with the file's parent and
            # DRIVER SCRIPT with the filename.
            proj_input.value = str(event.path.parent)
            script_input.value = event.path.name
            save_recent_path(event.path.parent)
        elif not script_val:
            # PROJECT DIR set but no driver script yet — fill DRIVER SCRIPT.
            proj_dir = Path(proj_val).expanduser().resolve()
            try:
                script_input.value = str(event.path.relative_to(proj_dir))
            except ValueError:
                script_input.value = str(event.path)
        else:
            # Both already set — append to EXTRA FILES (comma-separated).
            extra_input = submit.query_one("#extra-files-input", Input)
            proj_dir = Path(proj_val).expanduser().resolve()
            try:
                new_entry = str(event.path.relative_to(proj_dir))
            except ValueError:
                new_entry = str(event.path)
            existing = extra_input.value.strip()
            extra_input.value = f"{existing}, {new_entry}" if existing else new_entry

        # Switch to Submit tab so the user sees the result immediately.
        self.query_one(TabbedContent).active = "submit"
