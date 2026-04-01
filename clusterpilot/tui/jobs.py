"""F1 JOBS view — job list + detail panel + action buttons."""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from typing import TYPE_CHECKING, cast

import aiosqlite
from textual import on, work
from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Button, Label, ListItem, ListView, RichLog, Static

from clusterpilot.cluster.slurm import TERMINAL_STATES, cancel, cat_log, find_log, job_status, tail_log
from clusterpilot.db import DB_PATH, JobRecord, delete_job, get_all_jobs, init_db, mark_remote_cleaned, update_status
from clusterpilot.jobs.ai_gen import _PRICING
from clusterpilot.jobs.sync import sync_job
from clusterpilot.ssh.connection import SSHError, is_connected, remove_remote_dir
from clusterpilot.ssh.rsync import download

log = logging.getLogger(__name__)

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
    # Per-job API cost (if usage was recorded).
    if job.input_tokens or job.output_tokens:
        inp_rate, out_rate = _PRICING.get(job.model_used, (3.00, 15.00))
        cost = (job.input_tokens * inp_rate + job.output_tokens * out_rate) / 1_000_000
        cost_str = f"[#e8a020]${cost:.4f}[/]"
    else:
        cost_str = "[#7a6a50]—[/]"

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
        ("CLEANED",   "[#6ed86e]yes[/]" if job.remote_cleaned else "[#7a6a50]no[/]"),
        ("AI COST",   cost_str),
    ]
    if job.array_spec:
        rows.insert(4, ("ARRAY", f"[#e8a020]{job.array_spec}[/]"))
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
                yield Button("  [L] LOG    ", id="btn-log",   variant="default")
                yield Button("  [C] CLEAN  ", id="btn-clean",  variant="default")
                yield Button("  [D] DELETE ", id="btn-delete", variant="default")

    def on_mount(self) -> None:
        self._jobs: list[JobRecord] = []
        self._selected: int = 0
        self._log_dirty: bool = False   # True when user-triggered content is showing
        self._tail_timer: object | None = None   # live-polling timer handle
        self._tail_job_id: str | None = None     # job ID being tailed
        self._tail_log_path: str | None = None   # cached log path for polling
        self._tail_mode: str = "tail"             # "tail" or "full"
        self._clean_confirm_id: str | None = None  # job_id awaiting clean confirmation
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
        # CLEAN: only for terminal jobs that still have a remote directory.
        self.query_one("#btn-clean", Button).disabled = (
            not terminal or job.remote_cleaned or not job.working_dir
        )

    def _show_detail(self, job: JobRecord) -> None:
        """Full detail update — metadata + reset the log panel (user selected a new job)."""
        self._stop_tail_polling()
        self._clean_confirm_id = None
        self._update_meta(job)
        self._log_dirty = False
        log_widget = self.query_one("#log-display", RichLog)
        log_widget.clear()
        log_widget.write(f"[#7a6a50]Select [T] TAIL to fetch live output.[/]")

    def _stop_tail_polling(self) -> None:
        """Cancel any active log-polling timer."""
        if self._tail_timer is not None:
            self._tail_timer.stop()
            self._tail_timer = None
        self._tail_job_id = None
        self._tail_log_path = None

    def _start_tail_polling(self, job: JobRecord, log_path: str, mode: str) -> None:
        """Begin polling the log every 5 seconds for a running job."""
        self._stop_tail_polling()
        self._tail_job_id = job.job_id
        self._tail_log_path = log_path
        self._tail_mode = mode
        self._tail_timer = self.set_interval(5, self._poll_tail)

    @work(thread=False)
    async def _poll_tail(self) -> None:
        """Re-fetch log for the currently tailed job."""
        if not self._tail_job_id or not self._tail_log_path:
            self._stop_tail_polling()
            return
        # Find the job record — stop if gone or terminal.
        job = None
        for j in self._jobs:
            if j.job_id == self._tail_job_id:
                job = j
                break
        if job is None or job.status in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
            self._stop_tail_polling()
            return
        app = cast("ClusterPilotApp", self.app)
        profile = app._config.get_cluster(job.cluster_name)
        if not profile or not is_connected(profile.host, profile.user):
            return
        log_widget = self.query_one("#log-display", RichLog)
        if self._tail_mode == "tail":
            lines = await tail_log(profile.host, profile.user, self._tail_log_path, n_lines=500)
        else:
            lines = await cat_log(profile.host, profile.user, self._tail_log_path)
        if not lines:
            return
        log_widget.clear()
        total = len(lines.splitlines())
        label = "last 500 lines" if self._tail_mode == "tail" else f"{total} lines"
        log_widget.write(f"[#7a6a50]── {self._tail_log_path} ({label}) ── [dim]live[/dim][/]")
        for line in lines.splitlines():
            color = "#e05050" if ("ERROR" in line or "error" in line) else \
                    "#6ed86e" if ("\u2713" in line or "successfully" in line) else "#f0e8d0"
            log_widget.write(f"[{color}]{line}[/]")

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
        if not app.ensure_connected(profile):
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
            self.app.notify(f"rsync failed: {exc}", severity="error", markup=False)

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
        if not app.ensure_connected(profile):
            return
        try:
            await cancel(profile.host, profile.user, job.job_id)
            self.app.notify(f"scancel {job.job_id} sent.", severity="warning")
        except Exception as exc:
            self.app.notify(f"Kill failed: {exc}", severity="error", markup=False)
            return

        # Give SLURM a moment to process the cancellation, then immediately
        # update the local DB and sync — no need to wait for the next daemon poll.
        await asyncio.sleep(3)
        try:
            new_status = await job_status(profile.host, profile.user, job.job_id)
            if new_status and new_status != job.status:
                now = time.time()
                async with aiosqlite.connect(app._db_path) as db:
                    await init_db(db)
                    await update_status(
                        db, job.job_id, job.cluster_name, new_status,
                        finished_at=now if new_status in TERMINAL_STATES else None,
                    )
                updated = dataclasses.replace(
                    job, status=new_status,
                    finished_at=now if new_status in TERMINAL_STATES else job.finished_at,
                )
                # Fetch the log tail for the dashboard.
                log_tail: str | None = None
                log_path = job.log_path
                if not log_path:
                    try:
                        log_path = await find_log(
                            profile.host, profile.user,
                            job.job_name, job.job_id, job.working_dir,
                        )
                    except Exception:
                        pass
                if log_path:
                    try:
                        log_tail = await tail_log(profile.host, profile.user, log_path)
                    except Exception:
                        pass
                await sync_job(updated, new_status, app._config.hosted, log_tail=log_tail)
        except Exception:
            log.warning("Post-kill status check failed for %s — daemon will catch it", job.job_id, exc_info=True)

        self._refresh()

    @on(Button.Pressed, "#btn-tail")
    def action_tail(self) -> None:
        if not self._jobs:
            return
        self._do_tail(self._jobs[self._selected])

    @work(thread=False)
    async def _do_tail(self, job: JobRecord) -> None:
        self._stop_tail_polling()
        app = cast("ClusterPilotApp", self.app)
        profile = app._config.get_cluster(job.cluster_name)
        if not profile or not app.ensure_connected(profile):
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
        lines = await tail_log(profile.host, profile.user, log_path, n_lines=500)
        live_tag = " [dim]live[/dim]" if job.status == "RUNNING" else ""
        log_widget.write(f"[#7a6a50]── {log_path} (last 500 lines) ──{live_tag}[/]")
        for line in lines.splitlines():
            color = "#e05050" if ("ERROR" in line or "error" in line) else \
                    "#6ed86e" if ("\u2713" in line or "successfully" in line) else "#f0e8d0"
            log_widget.write(f"[{color}]{line}[/]")
        # Start live polling if the job is still running.
        if job.status == "RUNNING":
            self._start_tail_polling(job, log_path, "tail")

    # ── Full log ──────────────────────────────────────────────────────────────

    @on(Button.Pressed, "#btn-log")
    def action_log(self) -> None:
        if not self._jobs:
            return
        self._do_full_log(self._jobs[self._selected])

    @work(thread=False)
    async def _do_full_log(self, job: JobRecord) -> None:
        self._stop_tail_polling()
        app = cast("ClusterPilotApp", self.app)
        profile = app._config.get_cluster(job.cluster_name)
        if not profile or not app.ensure_connected(profile):
            return
        log_widget = self.query_one("#log-display", RichLog)
        log_widget.clear()
        self._log_dirty = True
        log_path = job.log_path
        if not log_path:
            log_path = await find_log(
                profile.host, profile.user,
                job.job_name, job.job_id, job.working_dir,
            )
        if not log_path:
            log_widget.write("[#7a6a50]Log file not found yet.[/]")
            return
        log_widget.write(f"[#e8a020]Fetching full log…[/]")
        content = await cat_log(profile.host, profile.user, log_path)
        log_widget.clear()
        total = len(content.splitlines())
        live_tag = " [dim]live[/dim]" if job.status == "RUNNING" else ""
        log_widget.write(f"[#7a6a50]── {log_path} ({total} lines) ──{live_tag}[/]")
        for line in content.splitlines():
            color = "#e05050" if ("ERROR" in line or "error" in line) else \
                    "#6ed86e" if ("\u2713" in line or "successfully" in line) else "#f0e8d0"
            log_widget.write(f"[{color}]{line}[/]")
        # Start live polling if the job is still running.
        if job.status == "RUNNING":
            self._start_tail_polling(job, log_path, "full")

    # ── Clean remote working directory ────────────────────────────────────────

    @on(Button.Pressed, "#btn-clean")
    def action_clean(self) -> None:
        if not self._jobs:
            return
        job = self._jobs[self._selected]
        log_widget = self.query_one("#log-display", RichLog)

        if not job.synced and self._clean_confirm_id != job.job_id:
            # First press with unsynced results: warn and ask for confirmation.
            self._clean_confirm_id = job.job_id
            log_widget.clear()
            self._log_dirty = True
            log_widget.write(
                "[#e8a020]⚠ Results have not been synced to your local machine.[/]\n"
                "[#7a6a50]Press [C] CLEAN again to delete the remote directory anyway.[/]"
            )
            return

        self._clean_confirm_id = None
        self._do_clean(job)

    @work(thread=False)
    async def _do_clean(self, job: JobRecord) -> None:
        app = cast("ClusterPilotApp", self.app)
        profile = app._config.get_cluster(job.cluster_name)
        if not profile:
            self.app.notify("Cluster not in config.", severity="error")
            return
        if not app.ensure_connected(profile):
            return
        log_widget = self.query_one("#log-display", RichLog)
        log_widget.clear()
        self._log_dirty = True
        log_widget.write(f"[#e8a020]Deleting {job.working_dir} …[/]")
        try:
            await remove_remote_dir(profile.host, profile.user, job.working_dir)
        except SSHError as exc:
            log_widget.write(f"[#e05050]Failed: {exc}[/]")
            self.app.notify(f"Clean failed: {exc}", severity="error", markup=False)
            return
        async with aiosqlite.connect(app._db_path) as db:
            await init_db(db)
            await mark_remote_cleaned(db, job.job_id, job.cluster_name)
        log_widget.write("[#6ed86e]✓ Remote directory deleted.[/]")
        self.app.notify(
            f"Cleaned {job.job_name} — remote directory removed.",
            severity="information",
        )
        self._refresh()

    # ── Delete job from history ───────────────────────────────────────────────

    @on(Button.Pressed, "#btn-delete")
    def action_delete(self) -> None:
        if not self._jobs:
            return
        job = self._jobs[self._selected]
        if job.status in ("PENDING", "RUNNING"):
            self.app.notify(
                "Cannot delete an active job — kill it first.",
                severity="warning",
            )
            return
        self._do_delete(job)

    @work(thread=False)
    async def _do_delete(self, job: JobRecord) -> None:
        app = cast("ClusterPilotApp", self.app)
        async with aiosqlite.connect(app._db_path) as db:
            await init_db(db)
            await delete_job(db, job.job_id, job.cluster_name)
        self.app.notify(
            f"Removed {job.job_name} (#{job.job_id}) from history.",
            severity="information",
        )
        # Adjust selection index and refresh the list.
        if self._selected > 0:
            self._selected -= 1
        self._log_dirty = False
        self._refresh()
