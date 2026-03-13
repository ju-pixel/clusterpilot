"""ClusterPilot Textual application."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiosqlite
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, Label, Static, TabbedContent, TabPane

from clusterpilot.config import Config
from clusterpilot.db import DB_PATH, get_total_usage, init_db
from clusterpilot.jobs.ai_gen import _PRICING
from clusterpilot.jobs.daemon import PollDaemon
from clusterpilot.ssh.connection import is_connected, open_connection
from clusterpilot.tui.config_view import ConfigView
from clusterpilot.tui.jobs import JobsView
from clusterpilot.tui.submit import SubmitView
from clusterpilot.tui.widgets.file_explorer import FileExplorer, save_recent_path

log = logging.getLogger(__name__)


class TitleBar(Static):
    def __init__(self, config: Config) -> None:
        self._config = config
        self._cost_text = ""
        super().__init__(self._render())

    def _render(self) -> str:
        clusters = "  ".join(
            f"[#6ed86e]●[/] {c.name}" for c in self._config.clusters
        )
        cost = f"  [#3d3520]│[/]  {self._cost_text}" if self._cost_text else ""
        return (
            f"[bold #e8a020]◈ CLUSTERPILOT[/]  [#7a6a50]v0.1.0-dev[/]  "
            f"[#3d3520]│[/]  {clusters}{cost}"
        )

    def set_cost(self, cost_usd: float) -> None:
        self._cost_text = f"[#7a6a50]API spend:[/] [#e8a020]${cost_usd:.4f}[/]"
        self.update(self._render())


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


class ClusterPilotApp(App):
    """ClusterPilot terminal UI — amber phosphor edition."""

    TITLE = "ClusterPilot"
    SUB_TITLE = "AI-assisted HPC workflow"

    BINDINGS = [
        Binding("f1", "show_jobs", "Jobs", show=False),
        Binding("f2", "show_submit", "Submit", show=False),
        Binding("f3", "toggle_explorer", "Files", show=False),
        Binding("f9", "show_config", "Config", show=False),
        Binding("q", "quit", "Quit", show=False),
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
    border: tall $amberDim;
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
    height: 10;
    border: tall $amberDim;
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
    height: 1fr;
}

#log-panel {
    height: 1fr;
    margin-top: 1;
    border: tall $amberDim;
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

#action-bar {
    height: 3;
    margin-top: 1;
    layout: horizontal;
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
    border: tall $amberDim;
    background: $bg;
    height: auto;
    padding: 1;
}

#describe-title {
    color: $amber;
    text-style: bold;
    margin-bottom: 1;
}

#partition-row {
    height: auto;
    margin-bottom: 1;
    layout: horizontal;
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
    margin-bottom: 1;
    layout: horizontal;
}

#extra-files-input {
    width: 1fr;
    background: $bg3;
    border: tall $border2;
    color: $white;
}

#extra-files-input:focus {
    border: tall $amberDim;
}

.field-label {
    width: 12;
    color: $dim;
    text-style: bold;
    height: 3;
    content-align: left middle;
}

#partition-select {
    width: 1fr;
    background: $bg3;
    border: tall $border2;
    color: $white;
}

#partition-select:focus {
    border: tall $amberDim;
}

Select > SelectCurrent {
    background: $bg3;
    color: $white;
    border: tall $border2;
}

Select.-focus > SelectCurrent {
    border: tall $amberDim;
}

SelectOverlay {
    background: $bg2;
    border: tall $amberDim;
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
    border: tall $border2;
    color: $white;
}

#project-dir-input:focus {
    border: tall $amberDim;
}

#script-path-input {
    width: 1fr;
    background: $bg3;
    border: tall $border2;
    color: $white;
}

#script-path-input:focus {
    border: tall $amberDim;
}

#field-help {
    height: auto;
    max-height: 8;
    margin-top: 1;
    padding: 0 1;
    color: $dim;
    background: $bg;
}

#description-input {
    border: tall $border2;
    background: $bg3;
    color: $white;
    height: 7;
}

#description-input:focus {
    border: tall $amberDim;
}

#generate-row {
    height: 3;
    margin-top: 1;
    layout: horizontal;
    align: right middle;
}

#btn-generate {
    background: $amberLo;
    color: $amber;
    border: tall $amberDim;
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
    border: tall $greenDim;
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

#submit-actions {
    height: 3;
    margin-top: 1;
    layout: horizontal;
}

#btn-submit {
    background: $greenDim;
    color: $green;
    border: tall $green;
    text-style: bold;
    width: 2fr;
}

#btn-submit:hover { background: #1a5a1a; }
#btn-submit:disabled { background: $dimmer; color: $dim; border: tall $dimmer; }
#btn-edit-script { width: 1fr; }
#btn-save { width: 1fr; }
#btn-clear { width: 1fr; }

/* ── Config view ────────────────────────── */
ConfigView {
    layout: vertical;
    background: $bg;
    padding: 1;
    overflow: auto;
    scrollbar-color: $amberDim;
}

.cfg-section {
    border: tall $amberDim;
    background: $bg;
    padding: 1;
    margin-bottom: 1;
    height: auto;
}

#config-content {
    height: auto;
}

#config-actions {
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
    border: tall $border2;
    color: $white;
    height: 3;
}

#explorer-path-input:focus {
    border: tall $amberDim;
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

/* ── Shared ─────────────────────────────── */
Button {
    background: $bg3;
    color: $amber;
    border: tall $amberDim;
    margin-right: 1;
}

Button:hover { background: $amberLo; }
Button.-error { color: $red; border: tall $redDim; background: $redDim; }
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
        yield StatusBar()

    async def on_mount(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await init_db(db)
        await self._ensure_connections()
        self._start_daemon()
        await self._refresh_cost()
        self.set_interval(30, self._refresh_cost)

    async def _refresh_cost(self) -> None:
        """Update the title bar with cumulative API spend."""
        async with aiosqlite.connect(self._db_path) as db:
            await init_db(db)
            inp, out = await get_total_usage(db)
        # Use default sonnet pricing for the aggregate (good enough for display).
        inp_rate, out_rate = _PRICING.get(self._config.model, (3.00, 15.00))
        cost = (inp * inp_rate + out * out_rate) / 1_000_000
        self.query_one(TitleBar).set_cost(cost)

    async def _ensure_connections(self) -> None:
        for profile in self._config.clusters:
            if is_connected(profile.host, profile.user):
                continue
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
            except Exception as exc:
                self.notify(
                    f"SSH failed ({profile.host}): {exc}",
                    severity="error",
                    timeout=20,
                )

    def _start_daemon(self) -> None:
        daemon = PollDaemon(self._config, self._db_path)
        self._daemon_task = asyncio.get_event_loop().create_task(
            daemon.run_forever()
        )
        log.debug("Poll daemon started")

    async def on_unmount(self) -> None:
        if self._daemon_task:
            self._daemon_task.cancel()

    # ── Tab navigation ────────────────────────────────────────────────────────

    def action_show_jobs(self) -> None:
        self.query_one(TabbedContent).active = "jobs"

    def action_show_submit(self) -> None:
        self.query_one(TabbedContent).active = "submit"

    def action_show_config(self) -> None:
        self.query_one(TabbedContent).active = "config"

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
