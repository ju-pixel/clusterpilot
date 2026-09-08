"""F1 JOBS view — job list + detail panel + action buttons."""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

import aiosqlite
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Label, ListItem, ListView, RichLog, Static

from clusterpilot.cluster.slurm import (
    RUNNING_STATES,
    TERMINAL_STATES,
    array_task_states,
    format_summary,
    parse_summary,
    cancel,
    cat_log,
    find_array_logs,
    find_log,
    job_status,
    tail_log,
)
from clusterpilot.db import DB_PATH, JobRecord, delete_job, get_all_jobs, init_db, mark_remote_cleaned, update_status
from clusterpilot.jobs.ai_gen import estimate_cost
from clusterpilot.jobs.fieldnotes import log_completed_job
from clusterpilot.jobs.sync import sync_job
from clusterpilot.ssh.connection import SSHError, is_connected, remove_remote_dir
from clusterpilot.ssh.rsync import download
from clusterpilot.tui.widgets.confirm import ConfirmScreen

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from clusterpilot.tui.app import ClusterPilotApp

_STATUS_STYLE = {
    "RUNNING":   ("[#6ed86e]", "▶"),
    "PENDING":   ("[#e8a020]", "◈"),
    "COMPLETED": ("[#50c8c8]", "✓"),
    "FAILED":    ("[#e05050]", "✗"),
    "CANCELLED": ("[#e05050]", "✗"),
    "TIMEOUT":   ("[#e05050]", "⏰"),
    "OUT_OF_MEMORY": ("[#e05050]", "✗"),
    "NODE_FAIL":     ("[#e05050]", "✗"),
}


def _status_rich(status: str) -> str:
    color, icon = _STATUS_STYLE.get(status, ("[#f0e8d0]", "?"))
    return f"{color}{icon} {status}[/]"


# Seconds a task-state snapshot is reused for. TAIL is a key the user leans
# on, and two SSH round trips per press on a 54-task array is a slow key.
_ARRAY_SNAPSHOT_TTL = 30.0

# The two groups a log press can cycle. TAIL asks "what is happening", LOG
# asks "what went wrong", and those are different sets of tasks (#73).
_RUNNING = "running"
_FINISHED = "finished"


@dataclasses.dataclass(frozen=True)
class ArrayLogChoice:
    """Which array task's log to show, and how it sits among its siblings.

    ``log_path`` is empty when nothing matched, which is an ordinary state
    rather than an error: an array can have nothing running yet, or nothing
    finished yet. Saying so beats showing another task's log as though it
    were the one asked for.
    """

    want: str = _RUNNING
    log_path: str = ""
    task: str = ""
    matched: int = 0    # tasks in the cycle this choice came from
    total: int = 0      # tasks in the array, as far as logs and squeue show


def _elapsed(job: JobRecord) -> str:
    if job.started_at is None:
        return "─:──:──"
    secs = int((job.finished_at or time.time()) - job.started_at)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


# Usable columns inside #queue-panel: 34 wide less its two border columns.
_ROW_WIDTH = 32


def _format_list_item(job: JobRecord) -> str:
    """Two lines: name and breakdown, then id, cluster and state glyph.

    The per-task breakdown belongs on the row, not only in the detail pane.
    With four arrays across four clusters, opening each one in turn to learn
    how far it has got is what sends you to ssh instead.

    It goes on the name line rather than after the cluster because the second
    line is already close to the panel's width: a `trillium-gpu` row with a
    breakdown like `120R/880PD` would push it past 32 columns and Textual
    would clip the right-hand end, which is precisely the number being added.
    On the name line the name gives way instead, which costs less.
    """
    color, icon = _STATUS_STYLE.get(job.status, ("[#f0e8d0]", "?"))
    detail = job.status_detail or ""
    if detail:
        name_width = max(12, _ROW_WIDTH - len(detail) - 3)
        name = job.job_name[:name_width]
        head = f" [bold]{name}[/]  [#7a6a50]{detail}[/]"
    else:
        head = f" [bold]{job.job_name[:26]}[/]"
    return (
        f"{head}\n"
        f" [#7a6a50]#{job.job_id}  {job.cluster_name}[/]  "
        f"{color}{icon}[/]"
    )


def _queue_title(jobs: list[JobRecord]) -> str:
    """QUEUE header carrying the total task breakdown across active jobs.

    The question this answers is "how many of my tasks are running right now",
    which otherwise means logging into every cluster in turn. Only active jobs
    count: finished ones would bury the live numbers under a growing pile of
    completions.
    """
    totals: dict[str, int] = {}
    for job in jobs:
        if job.status in TERMINAL_STATES:
            continue
        for state, count in parse_summary(job.status_detail or "").items():
            totals[state] = totals.get(state, 0) + count
    if not totals:
        return "═ QUEUE "
    return f"═ QUEUE  [#e8a020]{format_summary(totals)}[/] "


def _display_path(path: str) -> str:
    """A local path with the home directory shortened to ``~``."""
    if not path:
        return "(not recorded)"
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path


def _format_meta(job: JobRecord) -> str:
    # Per-job API cost, for the generation that produced the submitted script.
    # An unpriced model says so rather than borrowing another model's rate: the
    # old fallback billed a free local generation at Sonnet 4.6's price (#67).
    if job.input_tokens or job.output_tokens:
        cost = estimate_cost(job.model_used, job.input_tokens, job.output_tokens)
        if cost is None:
            cost_str = f"[#7a6a50]not priced ({job.model_used or 'unknown model'})[/]"
        else:
            cost_str = f"[#e8a020]${cost:.4f}[/]"
    else:
        cost_str = "[#7a6a50]—[/]"

    rows = [
        ("NAME",      f"[bold #e8a020]{job.job_name}[/]"),
        ("STATUS",    _status_rich(job.status) + (
                          f" [#7a6a50]{job.status_detail}[/]" if job.status_detail else ""
                      )),
        ("CLUSTER",   f"[#50c8c8]{job.cluster_name}[/]"),
        ("PARTITION", job.partition),
        ("ACCOUNT",   f"[#7a6a50]{job.account}[/]"),
        ("ELAPSED",   f"[#6ed86e]{_elapsed(job)}[/]" if job.status == "RUNNING"
                      else f"[#7a6a50]{_elapsed(job)}[/]"),
        ("WALLTIME",  job.walltime),
        ("SYNCED",    "[#6ed86e]yes[/]" if job.synced else "[#7a6a50]no[/]"),
        ("CLEANED",   "[#6ed86e]yes[/]" if job.remote_cleaned else "[#7a6a50]no[/]"),
        ("AI COST",   cost_str),
        # Where RSYNC puts this job's results. Without it the destination was
        # invisible in the TUI, and it is not always the directory the user
        # launched from.
        ("RESULTS",   f"[#7a6a50]{_display_path(job.local_dir)}[/]"),
    ]
    # Only present once seff has answered, which is after the job is terminal.
    if job.efficiency:
        rows.append(("EFFICIENCY", f"[#7a6a50]{job.efficiency}[/]"))
    if job.array_spec:
        rows.insert(4, ("ARRAY", f"[#e8a020]{job.array_spec}[/]"))
    return "  ".join(f"[#7a6a50]{k}[/] {v}" for k, v in rows[:4]) + "\n" + \
           "  ".join(f"[#7a6a50]{k}[/] {v}" for k, v in rows[4:])


class JobsView(Static):
    """Two-column jobs view: list on left, detail on right."""

    # The bracketed letters on the buttons are real keys: they fire whenever
    # focus is anywhere inside this view.
    BINDINGS = [
        Binding("r", "rsync", "Rsync", show=False),
        Binding("k", "kill", "Kill", show=False),
        Binding("t", "tail", "Tail", show=False),
        Binding("l", "log", "Log", show=False),
        Binding("c", "clean", "Clean remote", show=False),
        Binding("d", "delete", "Forget", show=False),
        Binding("y", "copy_log", "Copy log", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="queue-panel"):
            yield Label("═ QUEUE ", id="queue-title")
            yield ListView(id="job-list")
        with Vertical(id="detail-col"):
            with Vertical(id="meta-panel"):
                yield Label("═ JOB DETAIL ", id="meta-title")
                yield Static("Select a job from the queue.", id="meta-content")
            with Vertical(id="log-panel"):
                yield Label(r"═ OUTPUT LOG  \[Y] copy ", id="log-title")
                yield RichLog(id="log-display", highlight=False, markup=True)
            with Vertical(id="action-bar"):
                # The brackets are escaped: a button label is parsed as
                # Textual markup, which would otherwise swallow "[R]".
                yield Button(r"\[R] RSYNC", id="btn-rsync", variant="default")
                yield Button(r"\[K] KILL", id="btn-kill", variant="default")
                yield Button(r"\[T] TAIL", id="btn-tail", variant="default")
                yield Button(r"\[L] LOG", id="btn-log", variant="default")
                yield Button(r"\[C] CLEAN REMOTE", id="btn-clean", variant="default")
                yield Button(r"\[D] FORGET", id="btn-delete", variant="default")

    def on_mount(self) -> None:
        self._jobs: list[JobRecord] = []
        self._selected: int = 0
        self._tail_timer: object | None = None   # live-polling timer handle
        self._tail_job_id: str | None = None     # job ID being tailed
        self._tail_log_path: str | None = None   # cached log path for polling
        self._tail_mode: str = "tail"             # "tail" or "full"
        # The array task on screen, None for a plain job.
        self._tail_array_choice: ArrayLogChoice | None = None
        # Active array job's per-task logs and queue states, with one cursor
        # per group: TAIL cycles the running tasks, LOG the finished ones.
        self._array_job_id: str | None = None     # job the snapshot belongs to
        self._array_tasks: dict[str, str] = {}    # task index → log path
        self._array_states: dict[str, str] = {}   # task index → state in squeue
        self._array_fetched_at: float = 0.0       # monotonic clock, for the TTL
        self._array_pos: dict[str, int] = {}      # group → cursor, -1 before use
        self.set_interval(10, self._refresh)
        self._refresh()
        self.focus_job_list()

    def focus_job_list(self) -> None:
        """Move focus to the queue so the single-letter action keys work."""
        try:
            self.query_one("#job-list", ListView).focus()
        except NoMatches:
            pass

    async def select_job(self, job_id: str, cluster_name: str) -> None:
        """Reload the list from the database and select one job.

        Used by the submit hand-off: F1 should open on the job that was just
        submitted, with its detail pane already filled in, rather than on
        whatever happened to be selected before. A job the database does not
        know about leaves the selection alone.
        """
        async with aiosqlite.connect(self.app._db_path) as db:  # type: ignore[attr-defined]
            await init_db(db)
            self._jobs = await get_all_jobs(db, limit=100)
        for index, job in enumerate(self._jobs):
            if job.job_id == job_id and job.cluster_name == cluster_name:
                self._selected = index
                break
        self._selected = min(self._selected, max(len(self._jobs) - 1, 0))
        job_list = self.query_one("#job-list", ListView)
        await job_list.clear()
        # Awaited, unlike the timer refresh: the highlight can only be moved
        # once the rows are actually mounted.
        await job_list.extend(self._list_items())
        if not self._jobs:
            return
        job_list.index = self._selected
        self._show_detail(self._jobs[self._selected])
        self.focus_job_list()

    def running_jobs(self) -> list[JobRecord]:
        """Jobs in the list that are still running on a cluster."""
        return [j for j in getattr(self, "_jobs", []) if j.status == "RUNNING"]

    def _confirm(self, title: str, body: str, on_yes: "Callable[[], None]") -> None:
        """Ask before doing something irreversible; run *on_yes* if confirmed."""
        def _handle(confirmed: bool | None) -> None:
            if confirmed:
                on_yes()

        self.app.push_screen(ConfirmScreen(title, body), _handle)

    @work(thread=False)
    async def _refresh(self) -> None:
        async with aiosqlite.connect(self.app._db_path) as db:  # type: ignore[attr-defined]
            await init_db(db)
            jobs = await get_all_jobs(db, limit=100)
        self._jobs = jobs
        self._rebuild_list()

    def _list_items(self) -> list[ListItem]:
        """One list row per job, in the order the queue shows them."""
        return [ListItem(Static(_format_list_item(job))) for job in self._jobs]

    def _rebuild_list(self) -> None:
        self.query_one("#queue-title", Label).update(_queue_title(self._jobs))
        job_list = self.query_one("#job-list", ListView)
        job_list.clear()
        for item in self._list_items():
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
        terminal = job.status in TERMINAL_STATES
        self.query_one("#btn-kill", Button).disabled = terminal
        # RSYNC: enabled whenever there's something on the cluster worth pulling.
        # FAILED / CANCELLED / TIMEOUT / OUT_OF_MEMORY / NODE_FAIL jobs all have
        # logs the user usually wants for debugging, so they must be syncable.
        self.query_one("#btn-rsync", Button).disabled = (
            job.status == "PENDING"
            or job.remote_cleaned
            or not job.working_dir
        )
        # CLEAN: only for terminal jobs that still have a remote directory.
        self.query_one("#btn-clean", Button).disabled = (
            not terminal or job.remote_cleaned or not job.working_dir
        )

    def _show_detail(self, job: JobRecord) -> None:
        """Full detail update — metadata + reset the log panel (user selected a new job)."""
        self._stop_tail_polling()
        # Forget the previous job's array-task discovery so the next TAIL
        # re-discovers and starts at the lowest task.
        self._array_job_id = None
        self._array_tasks = {}
        self._array_states = {}
        self._array_fetched_at = 0.0
        self._array_pos = {}
        self._update_meta(job)
        log_widget = self.query_one("#log-display", RichLog)
        log_widget.clear()
        log_widget.write(r"[#7a6a50]Select \[T] TAIL to fetch live output.[/]")

    def _stop_tail_polling(self) -> None:
        """Cancel any active log-polling timer."""
        if self._tail_timer is not None:
            self._tail_timer.stop()
            self._tail_timer = None
        self._tail_job_id = None
        self._tail_log_path = None
        self._tail_array_choice = None

    def _start_tail_polling(
        self,
        job: JobRecord,
        log_path: str,
        mode: str,
        choice: ArrayLogChoice | None = None,
    ) -> None:
        """Begin polling the log every 5 seconds for a running job."""
        self._stop_tail_polling()
        self._tail_job_id = job.job_id
        self._tail_log_path = log_path
        self._tail_mode = mode
        self._tail_array_choice = choice
        self._tail_timer = self.set_interval(5, self._poll_tail)

    async def _array_snapshot(
        self, job: JobRecord, host: str, user: str,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """(task → log path, task → queue state) for *job*, briefly cached.

        Two SSH round trips, so a press within the TTL of the last one reuses
        what it found; a different job always refetches. The old code cached
        the discovery for as long as the job stayed selected, so a task that
        started after the first TAIL never appeared at all.
        """
        now = time.monotonic()
        if (
            self._array_job_id != job.job_id
            or now - self._array_fetched_at > _ARRAY_SNAPSHOT_TTL
        ):
            if self._array_job_id != job.job_id:
                self._array_pos = {}
            self._array_tasks = await find_array_logs(
                host, user, job.job_name, job.job_id, job.working_dir,
            )
            self._array_states = await array_task_states(host, user, job.job_id)
            self._array_job_id = job.job_id
            self._array_fetched_at = now
        return self._array_tasks, self._array_states

    async def _resolve_array_log(
        self, job: JobRecord, host: str, user: str, *, want: str,
    ) -> ArrayLogChoice:
        """Pick the next array task to show from the *want* group.

        TAIL cycles the tasks running now, LOG cycles the ones that have
        finished, because those are the two questions an array is asked: what
        is happening, and what went wrong. Both used to cycle every task that
        had ever written a log, so on a 54-task array TAIL kept landing on
        tasks that finished hours ago (#73).

        Deliberately free of widgets and notifications: the caller decides
        what to say when nothing matched, and this stays testable on its own.
        """
        tasks, states = await self._array_snapshot(job, host, user)
        total = len(set(tasks) | set(states))
        if want == _RUNNING:
            cycle = [t for t in tasks if states.get(t, "") in RUNNING_STATES]
        else:
            cycle = [t for t in tasks if t not in states]
        if not cycle:
            return ArrayLogChoice(want=want, total=total)

        # The cursor starts before the first task, so the first press of a
        # group shows the lowest task rather than the second one.
        position = (self._array_pos.get(want, -1) + 1) % len(cycle)
        self._array_pos[want] = position
        task = cycle[position]
        return ArrayLogChoice(
            want=want,
            log_path=tasks[task],
            task=task,
            matched=len(cycle),
            total=total,
        )

    def _log_header(
        self, log_path: str, label: str, choice: ArrayLogChoice | None = None,
    ) -> str:
        """Build the OUTPUT LOG header line, annotating the array task if any.

        The brackets are escaped because the header is written as markup.
        """
        if choice is None or not choice.task:
            return f"{log_path} ({label})"
        keys = r"\[T] cycles running, \[L] cycles finished"
        return (
            f"{log_path} (array task {choice.task}; {choice.want} "
            f"{choice.matched} of {choice.total}; {label}; {keys})"
        )

    @staticmethod
    def _no_array_task_message(choice: ArrayLogChoice) -> str:
        """What to show when the asked-for group of tasks is empty."""
        if choice.total == 0:
            return "[#7a6a50]Array task logs not found yet.[/]"
        if choice.want == _RUNNING:
            return (
                "[#7a6a50]No task of this array is running now. "
                r"Press \[L] to cycle the tasks that have finished.[/]"
            )
        return (
            "[#7a6a50]No task of this array has finished yet. "
            r"Press \[T] to cycle the tasks that are running.[/]"
        )

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
        if job is None or job.status in TERMINAL_STATES:
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
        header = self._log_header(self._tail_log_path, label, self._tail_array_choice)
        log_widget.write(f"[#7a6a50]── {header} ── [dim]live[/dim][/]")
        for line in lines.splitlines():
            color = "#e05050" if ("ERROR" in line or "error" in line) else \
                    "#6ed86e" if ("\u2713" in line or "successfully" in line) else "#f0e8d0"
            log_widget.write(f"[{color}]{line}[/]")

    # ── Action buttons ────────────────────────────────────────────────────────

    def action_copy_log(self) -> None:
        """Copy the OUTPUT LOG panel to the clipboard.

        A key rather than a mouse selection: RichLog is a ScrollView, so a drag
        inside it scrolls instead of selecting, and a selection could only ever
        reach the lines currently on screen. The log is usually taller than the
        panel, and the point of copying it is to paste the whole thing
        somewhere else (#65).

        The panel's own strips are the source, so what lands on the clipboard
        is exactly what is displayed, minus the colour markup. Textual sends it
        as OSC 52, which means this also works when the TUI is being driven
        over SSH.
        """
        log_widget = self.query_one("#log-display", RichLog)
        lines = [strip.text.rstrip() for strip in log_widget.lines]
        while lines and not lines[-1]:
            lines.pop()
        if not lines:
            self.app.notify("Nothing in the output log to copy.")
            return
        self.app.copy_to_clipboard("\n".join(lines) + "\n")
        count = len(lines)
        self.app.notify(
            f"Copied {count} {'line' if count == 1 else 'lines'} to the clipboard.",
        )

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
            # Best-effort: log the run into local Fieldnotes off the event loop.
            # The helper no-ops silently when disabled / absent / no manifest, so
            # a hiccup never turns a successful rsync into a visible error.
            try:
                logged = await asyncio.to_thread(log_completed_job, job, app._config)
                if logged:
                    self.app.notify("Logged to Fieldnotes", severity="information")
            except Exception:
                pass
        except Exception as exc:
            log_widget.write(f"[#e05050]rsync failed: {exc}[/]")
            self.app.notify(f"rsync failed: {exc}", severity="error", markup=False)

    @on(Button.Pressed, "#btn-kill")
    def action_kill(self) -> None:
        if not self._jobs:
            return
        job = self._jobs[self._selected]
        self._confirm(
            "KILL JOB",
            f"Cancel job {job.job_id} ({job.job_name}) on {job.cluster_name}? "
            "Anything it has written so far stays on the cluster.",
            lambda: self._do_kill(job),
        )

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
        # Resolve the log path. Array jobs write one log per task (%x-%A-%a),
        # so TAIL cycles the tasks that are running right now: the tail of a
        # task that finished hours ago is not what T is pressed for (#73).
        choice: ArrayLogChoice | None = None
        if job.array_spec:
            choice = await self._resolve_array_log(
                job, profile.host, profile.user, want=_RUNNING,
            )
            log_path = choice.log_path
            if not log_path:
                log_widget.write(self._no_array_task_message(choice))
                return
        else:
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
        header = self._log_header(log_path, "last 500 lines", choice)
        log_widget.write(f"[#7a6a50]── {header} ──{live_tag}[/]")
        for line in lines.splitlines():
            color = "#e05050" if ("ERROR" in line or "error" in line) else \
                    "#6ed86e" if ("\u2713" in line or "successfully" in line) else "#f0e8d0"
            log_widget.write(f"[{color}]{line}[/]")
        # Start live polling if the job is still running.
        if job.status == "RUNNING":
            self._start_tail_polling(job, log_path, "tail", choice)

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
        # Array jobs: LOG cycles the tasks that have finished, whose logs are
        # complete and are what a post-mortem is after. TAIL has the running
        # ones (#73).
        choice: ArrayLogChoice | None = None
        if job.array_spec:
            choice = await self._resolve_array_log(
                job, profile.host, profile.user, want=_FINISHED,
            )
            log_path = choice.log_path
            if not log_path:
                log_widget.write(self._no_array_task_message(choice))
                return
        else:
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
        # Poll, and say "live", only for a log that can still grow. An array
        # task shown here has already finished, however busy the rest of the
        # array is.
        polling = job.status == "RUNNING" and choice is None
        live_tag = " [dim]live[/dim]" if polling else ""
        header = self._log_header(log_path, f"{total} lines", choice)
        log_widget.write(f"[#7a6a50]── {header} ──{live_tag}[/]")
        for line in content.splitlines():
            color = "#e05050" if ("ERROR" in line or "error" in line) else \
                    "#6ed86e" if ("\u2713" in line or "successfully" in line) else "#f0e8d0"
            log_widget.write(f"[{color}]{line}[/]")
        if polling:
            self._start_tail_polling(job, log_path, "full")

    # ── Clean remote working directory ────────────────────────────────────────

    @on(Button.Pressed, "#btn-clean")
    def action_clean(self) -> None:
        if not self._jobs:
            return
        job = self._jobs[self._selected]
        body = (
            f"Remove the working directory {job.working_dir} on "
            f"{job.cluster_name}? The local record and any synced results stay."
        )
        if not job.synced:
            body += " These results have not been synced to this machine yet."
        self._confirm("CLEAN REMOTE DIRECTORY", body, lambda: self._do_clean(job))

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
        self._confirm(
            "FORGET JOB",
            f"Forget job {job.job_id} ({job.job_name}) from the local history? "
            "Nothing on the cluster is touched.",
            lambda: self._do_delete(job),
        )

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
        self._refresh()
