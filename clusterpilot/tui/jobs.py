"""F1 JOBS view — job list + detail panel + action buttons."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

import aiosqlite
from textual import on, work
from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Button, Label, ListItem, ListView, RichLog, Static

from clusterpilot.cluster.slurm import cancel, find_log, tail_log
from clusterpilot.db import DB_PATH, JobRecord, get_all_jobs, init_db
from clusterpilot.ssh.connection import SSHError, is_connected
from clusterpilot.ssh.rsync import download

if TYPE_CHECKING:
    from clusterpilot.tui.app import ClusterPilotApp

_STATUS_STYLE = {
    "RUNNING":   ("[#6ed86e]", "▶"),
    "PENDING":   ("[#e8a020]", "◈"),
    "COMPLETED": ("[#50c8c8]", "✓"),
    "FAILED":    ("[#e05050]", "✗"),
    "CANCELLED": ("[#e05050]", "✗"),
    "TIMEOUT":   ("[#e05050]", "⏰"),
}


def _status_rich(status: str) -> str:
    color, icon = _STATUS_STYLE.get(status, ("[#f0e8d0]", "?"))
    return f"{color}{icon} {status}[/]"


def _elapsed(job: JobRecord) -> str:
    if job.started_at is None:
        return "─:──:──"
    secs = int((job.finished_at or time.time()) - job.started_at)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _format_list_item(job: JobRecord) -> str:
    color, icon = _STATUS_STYLE.get(job.status, ("[#f0e8d0]", "?"))
    name = job.job_name[:26]
    return (
        f" [bold]{name}[/]\n"
        f" [#7a6a50]#{job.job_id[-6:]}  {job.cluster_name}[/]  "
        f"{color}{icon}[/]"
    )


def _format_meta(job: JobRecord) -> str:
    rows = [
        ("NAME",      f"[bold #e8a020]{job.job_name}[/]"),
        ("STATUS",    _status_rich(job.status)),
        ("CLUSTER",   f"[#50c8c8]{job.cluster_name}[/]"),
        ("PARTITION", job.partition),
        ("ACCOUNT",   f"[#7a6a50]{job.account}[/]"),
        ("ELAPSED",   f"[#6ed86e]{_elapsed(job)}[/]" if job.status == "RUNNING"
                      else f"[#7a6a50]{_elapsed(job)}[/]"),
        ("WALLTIME",  job.walltime),
        ("SYNCED",    "[#6ed86e]yes[/]" if job.synced else "[#7a6a50]no[/]"),
    ]
    return "  ".join(f"[#7a6a50]{k}[/] {v}" for k, v in rows[:4]) + "\n" + \
           "  ".join(f"[#7a6a50]{k}[/] {v}" for k, v in rows[4:])


class JobsView(Static):
    """Two-column jobs view: list on left, detail on right."""

    def compose(self) -> ComposeResult:
        with Vertical(id="queue-panel"):
            yield Label("═ QUEUE ", id="queue-title")
            yield ListView(id="job-list")
        with Vertical(id="detail-col"):
            with Vertical(id="meta-panel"):
                yield Label("═ JOB DETAIL ", id="meta-title")
                yield Static("Select a job from the queue.", id="meta-content")
            with Vertical(id="log-panel"):
                yield Label("═ OUTPUT LOG ", id="log-title")
                yield RichLog(id="log-display", highlight=False, markup=True)
            with Vertical(id="action-bar"):
                yield Button("  [R] RSYNC  ", id="btn-rsync", variant="default")
                yield Button("  [K] KILL   ", id="btn-kill",  variant="default")
                yield Button("  [T] TAIL   ", id="btn-tail",  variant="default")

    def on_mount(self) -> None:
        self._jobs: list[JobRecord] = []
        self._selected: int = 0
        self._log_dirty: bool = False   # True when user-triggered content is showing
        self.set_interval(10, self._refresh)
        self._refresh()

    @work(thread=False)
    async def _refresh(self) -> None:
        async with aiosqlite.connect(self.app._db_path) as db:  # type: ignore[attr-defined]
            await init_db(db)
            jobs = await get_all_jobs(db, limit=100)
        self._jobs = jobs
        self._rebuild_list()

    def _rebuild_list(self) -> None:
        job_list = self.query_one("#job-list", ListView)
        job_list.clear()
        for job in self._jobs:
            item = ListItem(Static(_format_list_item(job)))
            job_list.append(item)
        if self._jobs:
            # Update metadata (status, elapsed, etc.) but preserve the log
            # panel if the user triggered TAIL or RSYNC — those results should
            # persist until the user explicitly refreshes or selects another job.
            self._update_meta(self._jobs[self._selected])

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = list(self.query_one("#job-list", ListView).children).index(event.item)
        if 0 <= idx < len(self._jobs):
            self._selected = idx
            self._show_detail(self._jobs[idx])

    def _update_meta(self, job: JobRecord) -> None:
        """Refresh the metadata panel and button states without touching the log."""
        self.query_one("#meta-title", Label).update(f"═ JOB {job.job_id} ")
        self.query_one("#meta-content", Static).update(_format_meta(job))
        terminal = job.status in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT")
        self.query_one("#btn-kill", Button).disabled = terminal
        self.query_one("#btn-rsync", Button).disabled = job.status not in (
            "COMPLETED", "RUNNING"
        )

    def _show_detail(self, job: JobRecord) -> None:
        """Full detail update — metadata + reset the log panel (user selected a new job)."""
        self._update_meta(job)
        self._log_dirty = False
        log_widget = self.query_one("#log-display", RichLog)
        log_widget.clear()
        log_widget.write(f"[#7a6a50]Select [T] TAIL to fetch live output.[/]")

    # ── Action buttons ────────────────────────────────────────────────────────

    @on(Button.Pressed, "#btn-rsync")
    def action_rsync(self) -> None:
        if not self._jobs:
            return
        self._do_rsync(self._jobs[self._selected])

    @work(thread=False)
    async def _do_rsync(self, job: JobRecord) -> None:
        app = cast("ClusterPilotApp", self.app)
        profile = app._config.get_cluster(job.cluster_name)
        if not profile:
            self.app.notify("Cluster not in config.", severity="error")
            return
        log_widget = self.query_one("#log-display", RichLog)
        log_widget.clear()
        self._log_dirty = True
        log_widget.write("[#e8a020]Starting rsync…[/]")
        local = __import__("pathlib").Path(job.local_dir) / "results"
        try:
            await download(
                profile.host, profile.user, job.working_dir, local,
                excludes=list(app._config.defaults.download_excludes),
                progress_callback=lambda line: log_widget.write(f"[#7a6a50]{line}[/]"),
            )
            log_widget.write(f"[#6ed86e]✓ Synced to {local}[/]")
            self.app.notify(f"Results synced → {local}", severity="information")
        except Exception as exc:
            log_widget.write(f"[#e05050]rsync failed: {exc}[/]")
            self.app.notify(f"rsync failed: {exc}", severity="error")

    @on(Button.Pressed, "#btn-kill")
    def action_kill(self) -> None:
        if not self._jobs:
            return
        self._do_kill(self._jobs[self._selected])

    @work(thread=False)
    async def _do_kill(self, job: JobRecord) -> None:
        app = cast("ClusterPilotApp", self.app)
        profile = app._config.get_cluster(job.cluster_name)
        if not profile:
            return
        try:
            await cancel(profile.host, profile.user, job.job_id)
            self.app.notify(f"scancel {job.job_id} sent.", severity="warning")
            self._refresh()
        except Exception as exc:
            self.app.notify(f"Kill failed: {exc}", severity="error")

    @on(Button.Pressed, "#btn-tail")
    def action_tail(self) -> None:
        if not self._jobs:
            return
        self._do_tail(self._jobs[self._selected])

    @work(thread=False)
    async def _do_tail(self, job: JobRecord) -> None:
        app = cast("ClusterPilotApp", self.app)
        profile = app._config.get_cluster(job.cluster_name)
        if not profile or not is_connected(profile.host, profile.user):
            self.app.notify("Not connected to cluster.", severity="error")
            return
        log_widget = self.query_one("#log-display", RichLog)
        log_widget.clear()
        self._log_dirty = True
        # Find log path if not cached.
        log_path = job.log_path
        if not log_path:
            log_path = await find_log(
                profile.host, profile.user,
                job.job_name, job.job_id, job.working_dir,
            )
        if not log_path:
            log_widget.write("[#7a6a50]Log file not found yet.[/]")
            return
        lines = await tail_log(profile.host, profile.user, log_path, n_lines=80)
        log_widget.write(f"[#7a6a50]── {log_path} (last 80 lines) ──[/]")
        for line in lines.splitlines():
            color = "#e05050" if ("ERROR" in line or "error" in line) else \
                    "#6ed86e" if ("✓" in line or "successfully" in line) else "#f0e8d0"
            log_widget.write(f"[{color}]{line}[/]")
