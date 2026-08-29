"""SLURM commands: submit, poll status, cancel, fetch log output.

All functions require an active SSH ControlMaster socket.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from clusterpilot.ssh.connection import SSHError, run_remote

_SUBMITTED_RE = re.compile(r"Submitted batch job (\d+)")

# States that mean the job will never run again.
TERMINAL_STATES = frozenset({
    "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT",
    "OUT_OF_MEMORY", "NODE_FAIL",
})

# States that mean at least one task is on a node right now.
_RUNNING_LIKE = ("RUNNING", "COMPLETING")

# Worst-first severity used to pick the aggregate state of a finished array.
_FAILURE_SEVERITY = (
    "FAILED", "OUT_OF_MEMORY", "TIMEOUT", "NODE_FAIL", "CANCELLED",
)

# Short labels used in JobStatus.summary, e.g. "5R/27PD".
_ABBREVIATIONS = {
    "RUNNING": "R",
    "PENDING": "PD",
    "COMPLETING": "CG",
    "COMPLETED": "C",
    "FAILED": "F",
    "TIMEOUT": "TO",
    "OUT_OF_MEMORY": "OOM",
    "NODE_FAIL": "NF",
    "CANCELLED": "CA",
}

# Display order within each of the three summary groups.
_SUMMARY_ORDER = (
    "RUNNING", "COMPLETING",
    "PENDING",
    "COMPLETED", "FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "CANCELLED",
)


class SlurmError(SSHError):
    """Raised when a SLURM command fails unexpectedly."""


# ── Job submission ────────────────────────────────────────────────────────────

async def submit(
    host: str,
    user: str,
    remote_script_path: str,
    *,
    working_dir: str | None = None,
) -> str:
    """Run sbatch on remote_script_path. Returns the numeric job ID string.

    Args:
        host:               SSH hostname.
        user:               Remote username.
        remote_script_path: Absolute path to the .sh script on the cluster.
        working_dir:        If given, cd here before running sbatch.

    Raises:
        SlurmError: if sbatch output doesn't contain "Submitted batch job NNN".
    """
    cmd = f"sbatch {remote_script_path}"
    if working_dir:
        cmd = f"cd {working_dir} && {cmd}"
    try:
        output = await run_remote(host, user, cmd)
    except SSHError as exc:
        raise SlurmError(f"sbatch failed: {exc}") from exc

    match = _SUBMITTED_RE.search(output)
    if not match:
        raise SlurmError(f"Unexpected sbatch output: {output!r}")
    return match.group(1)


# ── Status polling ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class JobStatus:
    """Aggregate status of a job, which may be a whole array of tasks.

    Attributes:
        state:  Canonical aggregate state, one of the usual SLURM names.
        counts: Normalised state -> task count, e.g. {"RUNNING": 5, "PENDING": 27}.
        source: Which command produced this, "squeue" or "sacct".
    """

    state: str
    counts: dict[str, int] = field(default_factory=dict)
    source: str = ""

    @property
    def summary(self) -> str:
        """Compact per-state task breakdown, e.g. "5R/27PD" or "31C/1F".

        Empty when the job is a single record, so plain jobs show nothing extra.
        """
        if len(self.counts) <= 1 and sum(self.counts.values()) <= 1:
            return ""
        parts = [
            f"{self.counts[state]}{_ABBREVIATIONS.get(state, state)}"
            for state in sorted(self.counts, key=_summary_sort_key)
        ]
        return "/".join(parts)


def normalise_state(raw: str) -> str:
    """Reduce a raw SLURM state string to its bare canonical name.

    "CANCELLED by 12345" -> "CANCELLED"; "COMPLETED+" -> "COMPLETED".
    Returns an empty string when there is nothing to normalise.
    """
    token = raw.strip().split("+")[0].strip()
    if not token:
        return ""
    return token.split()[0]


def aggregate(states: Iterable[str]) -> str:
    """Collapse the states of every task in a job into one canonical state.

    A single distinct state passes straight through, so ordinary single-task
    jobs keep today's behaviour including unusual states such as SUSPENDED.
    Otherwise: anything still on a node wins, then anything still queued, then
    all-completed, and finally the worst failure by fixed severity.
    """
    distinct = {s for s in (normalise_state(raw) for raw in states) if s}
    if not distinct:
        return ""
    if len(distinct) == 1:
        return next(iter(distinct))
    if distinct & set(_RUNNING_LIKE):
        return "RUNNING"
    if distinct - TERMINAL_STATES:
        return "PENDING"
    if distinct == {"COMPLETED"}:
        return "COMPLETED"
    for state in _FAILURE_SEVERITY:
        if state in distinct:
            return state
    return sorted(distinct)[0]


async def query_status(host: str, user: str, job_id: str) -> JobStatus | None:
    """Return the aggregate JobStatus for job_id, or None if it cannot be found.

    Strategy:
    1. squeue (fast, in-memory) — works while the job is queued or running.
    2. sacct (historical records) — works after the job has left the queue.

    Both commands print one line per array task, so every line is parsed and
    aggregated. Trusting the first line alone reports a mixed array as whatever
    its lowest task happens to be doing.
    """
    # 1. squeue — job still in queue
    try:
        out = await run_remote(
            host, user,
            f"squeue -j {job_id} -h -o '%i|%T' 2>/dev/null",
        )
        counts = _parse_status_lines(out)
        if counts:
            return JobStatus(state=aggregate(counts), counts=counts, source="squeue")
    except SSHError:
        pass

    # 2. sacct — job already finished; -X = summary record only (no steps)
    try:
        out = await run_remote(
            host, user,
            f"sacct -j {job_id} -n -X -o JobID,State --parsable2 2>/dev/null",
        )
        counts = _parse_status_lines(out)
        if counts:
            return JobStatus(state=aggregate(counts), counts=counts, source="sacct")
    except SSHError:
        pass

    return None


async def job_status(host: str, user: str, job_id: str) -> str | None:
    """Return the SLURM state for job_id, or None if the job cannot be found.

    Thin wrapper over query_status for callers that only need the state.

    Common return values: PENDING, RUNNING, COMPLETED, FAILED,
    CANCELLED, TIMEOUT, OUT_OF_MEMORY.
    """
    status = await query_status(host, user, job_id)
    return status.state if status else None


def _summary_sort_key(state: str) -> tuple[int, int, str]:
    """Order summary entries: running-like, then pending-like, then terminal."""
    if state in _RUNNING_LIKE:
        group = 0
    elif state not in TERMINAL_STATES:
        group = 1
    else:
        group = 2
    rank = _SUMMARY_ORDER.index(state) if state in _SUMMARY_ORDER else len(_SUMMARY_ORDER)
    return (group, rank, state)


def _parse_status_lines(text: str) -> dict[str, int]:
    """Parse "<job id>|<STATE>" lines into normalised state -> task count.

    A line without a pipe is treated as a bare state with a count of one.
    Empty fields (sacct can print a trailing separator) are ignored.
    """
    counts: dict[str, int] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "|" in line:
            fields = [f.strip() for f in line.split("|") if f.strip()]
            if len(fields) < 2:
                continue
            count = _task_count(fields[0])
            state = normalise_state(fields[1])
        else:
            count = 1
            state = normalise_state(line)
        if not state:
            continue
        counts[state] = counts.get(state, 0) + count
    return counts


def _task_count(job_field: str) -> int:
    """Count the array tasks a squeue or sacct job id field stands for.

    "123" and "123_7" are one task each; "123_[5-31,40]" is 28; a "%N" throttle
    suffix such as "123_[5-31%5]" is stripped first.
    """
    start = job_field.find("[")
    end = job_field.find("]", start + 1)
    if start == -1 or end == -1:
        return 1
    body = job_field[start + 1:end].split("%")[0]
    total = 0
    for item in body.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item:
            low, _, high = item.partition("-")
            try:
                total += int(high) - int(low) + 1
            except ValueError:
                total += 1
        else:
            total += 1
    return total or 1


# ── Job control ───────────────────────────────────────────────────────────────

async def cancel(host: str, user: str, job_id: str) -> None:
    """Cancel a queued or running SLURM job via scancel."""
    try:
        await run_remote(host, user, f"scancel {job_id}")
    except SSHError as exc:
        raise SlurmError(f"scancel failed for job {job_id}: {exc}") from exc


# ── Log access ────────────────────────────────────────────────────────────────

async def tail_log(
    host: str,
    user: str,
    remote_log_path: str,
    n_lines: int = 50,
) -> str:
    """Return the last n_lines of a remote file. Empty string if not found."""
    try:
        return await run_remote(
            host, user,
            f"tail -n {n_lines} {remote_log_path} 2>/dev/null",
        )
    except SSHError:
        return ""


async def cat_log(
    host: str,
    user: str,
    remote_log_path: str,
) -> str:
    """Return the full contents of a remote log file. Empty string if not found."""
    try:
        return await run_remote(
            host, user,
            f"cat {remote_log_path} 2>/dev/null",
        )
    except SSHError:
        return ""


async def find_log(
    host: str,
    user: str,
    job_name: str,
    job_id: str,
    working_dir: str,
) -> str | None:
    """Locate the SLURM stdout log for this job on the remote host.

    Tries common naming patterns in order:
      <working_dir>/<job_name>-<job_id>.out   (ClusterPilot default: %x-%j.out)
      <working_dir>/slurm-<job_id>.out        (SLURM default)
      <working_dir>/<job_id>.out

    Returns the first path that exists, or None.
    """
    candidates = [
        f"{working_dir}/{job_name}-{job_id}.out",
        f"{working_dir}/slurm-{job_id}.out",
        f"{working_dir}/{job_id}.out",
    ]
    for path in candidates:
        try:
            out = await run_remote(
                host, user,
                f"test -f {path} && echo exists",
            )
            if out.strip() == "exists":
                return path
        except SSHError:
            continue
    return None


async def find_array_logs(
    host: str,
    user: str,
    job_name: str,
    job_id: str,
    working_dir: str,
) -> dict[str, str]:
    """Map array task index → stdout log path for a job array.

    Each array task writes its own log via the ``%x-%A-%a`` pattern, i.e.
    ``<working_dir>/<job_name>-<job_id>-<task>.out`` (the hyphen separator is
    enforced when the script is sanitised, and ``%A`` is the array master job
    ID, which is what ClusterPilot stores as ``job_id``). This lists the
    working directory and parses the task index out of every match.

    Returns ``{task_index: log_path}`` ordered by numeric task index, or an
    empty dict if no per-task logs exist yet (tasks not started, or directory
    gone).
    """
    pattern = f"{working_dir}/{job_name}-{job_id}-*.out"
    try:
        out = await run_remote(host, user, f"ls -1 {pattern} 2>/dev/null")
    except SSHError:
        return {}

    suffix_re = re.compile(rf"-{re.escape(job_id)}-([^/]+)\.out$")
    tasks: dict[str, str] = {}
    for line in out.strip().splitlines():
        path = line.strip()
        if not path:
            continue
        match = suffix_re.search(path)
        if match:
            tasks[match.group(1)] = path

    def _order(task: str) -> tuple[int, str]:
        # Numeric task indices sort naturally; anything odd sorts last.
        return (int(task), "") if task.isdigit() else (2**31, task)

    return {task: tasks[task] for task in sorted(tasks, key=_order)}


# ── Job efficiency (seff) ─────────────────────────────────────────────────────

# seff reports one percentage per resource, each against the amount reserved:
#   CPU Efficiency: 12.34% of 01:23:45 core-walltime
#   Memory Efficiency: 5.60% of 16.00 GB
_CPU_EFFICIENCY_RE = re.compile(r"^CPU Efficiency:\s*([\d.]+)%", re.MULTILINE)
_MEM_EFFICIENCY_RE = re.compile(
    r"^Memory Efficiency:\s*([\d.]+)%\s*of\s*([\d.]+)\s*(\S+)", re.MULTILINE
)


def _parse_efficiency(output: str) -> str:
    """Condense ``seff`` output into one short line, "" when it says nothing.

    Returns something like ``CPU 12%, mem 6% of 16 GB``. Either half is
    dropped when seff did not report it, which is normal: a job that never
    started has no CPU figure, and some sites build SLURM without job
    accounting for memory.
    """
    parts: list[str] = []

    cpu = _CPU_EFFICIENCY_RE.search(output)
    if cpu:
        parts.append(f"CPU {round(float(cpu.group(1)))}%")

    mem = _MEM_EFFICIENCY_RE.search(output)
    if mem:
        percent = round(float(mem.group(1)))
        reserved = round(float(mem.group(2)))
        parts.append(f"mem {percent}% of {reserved} {mem.group(3)}")

    return ", ".join(parts)


async def job_efficiency(host: str, user: str, job_id: str) -> str:
    """CPU and memory efficiency for a finished job, "" when unavailable.

    Best-effort by design and never raises: ``seff`` is a site-optional
    wrapper, it needs the accounting database, and it says nothing useful
    until the job has left the queue. A job with no efficiency line is not a
    problem worth interrupting a notification for.

    For an array, pass ``<job_id>_<task>``: seff reports per task, and asking
    it about the array master gives nothing.
    """
    try:
        output = await run_remote(host, user, f"seff {job_id} 2>/dev/null")
    except Exception:
        return ""
    return _parse_efficiency(output)


# ── Job accounting (sacct) ────────────────────────────────────────────────────

# AllocTRES is a comma-separated list of what the scheduler reserved, e.g.
#   billing=4,cpu=4,gres/gpu=1,mem=16G,node=1
# The GPU key is "gres/gpu" on every site seen so far, and typed requests
# append the model as a second key ("gres/gpu:a100=2"), so both forms count.
_TRES_GPU_KEYS = ("gres/gpu",)


@dataclass(frozen=True)
class JobAccounting:
    """What SLURM reserved for a job, and for how long.

    Per-task fields (``cpus``, ``gpus``, ``nodes``) describe one array task,
    because every task of an array is allocated identically. The ``_seconds``
    totals are summed over every task, so a 100-task array reports the whole
    array's reserved time. For a single-task job the two agree.

    Every field is optional: sacct is answering about a job that may still be
    queued, and a site may not record a given resource at all. ``None`` means
    "not reported", which is not the same as zero and must not be rendered as
    one.
    """

    cpus: int | None = None
    gpus: int | None = None
    nodes: int | None = None
    runtime_seconds: int | None = None   # longest task, so the job's wall duration
    core_seconds: float | None = None    # sum of cpus x elapsed over all tasks
    gpu_seconds: float | None = None     # sum of gpus x elapsed over all tasks
    exit_code: str = ""                  # worst task's "<code>:<signal>", e.g. "137:0"
    tasks: int = 0                       # accounting records summed

    @property
    def is_empty(self) -> bool:
        """True when sacct told us nothing worth storing."""
        return self.tasks == 0


def _parse_tres(raw: str) -> dict[str, float]:
    """Parse an AllocTRES string into a key -> number mapping.

    Unparseable entries are skipped rather than raising: this is one field of
    one line of a best-effort accounting query, and a site that formats it
    unusually must not cost us the rest of the record.
    """
    parsed: dict[str, float] = {}
    for entry in raw.split(","):
        key, sep, value = entry.strip().partition("=")
        if not sep:
            continue
        # Memory carries a unit suffix ("16G"); the numeric prefix is enough
        # for the resources we count, and mem is not one of them.
        match = re.match(r"^([\d.]+)", value.strip())
        if not match:
            continue
        try:
            parsed[key.strip().lower()] = float(match.group(1))
        except ValueError:
            continue
    return parsed


def _tres_gpus(tres: dict[str, float]) -> float | None:
    """GPU count from a parsed AllocTRES, or None when none was reserved.

    Handles both the untyped ``gres/gpu`` key and the typed ``gres/gpu:a100``
    form some sites emit alongside it. The typed keys are ignored when the
    plain one is present, because sacct reports both and summing them would
    double-count.
    """
    for key in _TRES_GPU_KEYS:
        if key in tres:
            return tres[key]
    typed = [v for k, v in tres.items() if k.startswith("gres/gpu:")]
    return sum(typed) if typed else None


def _worst_exit_code(codes: Iterable[str]) -> str:
    """Pick the exit code that best explains the job: the highest non-zero.

    sacct prints "<exit>:<signal>". A task killed by a signal reports exit 0
    with a non-zero signal, so both halves are compared and a signal outranks
    an exit code of the same value: being killed is more explanatory than
    exiting.
    """
    best = ""
    best_rank = (-1, -1)
    for code in codes:
        exit_part, _, signal_part = code.strip().partition(":")
        try:
            rank = (int(signal_part or 0), int(exit_part or 0))
        except ValueError:
            continue
        if rank > best_rank:
            best_rank = rank
            best = code.strip()
    return best


def _parse_accounting(text: str) -> JobAccounting:
    """Fold sacct's per-task lines into one JobAccounting.

    Expects "JobID|AllocTRES|ElapsedRaw|ExitCode" per line, as written by
    ``--parsable2``. Lines that cannot be read are skipped; a job whose tasks
    are all still queued yields zero elapsed time and no totals, which is
    correct rather than missing.
    """
    cpus: int | None = None
    gpus: int | None = None
    nodes: int | None = None
    longest: int | None = None
    core_seconds = 0.0
    gpu_seconds = 0.0
    codes: list[str] = []
    tasks = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or "|" not in line:
            continue
        fields = line.split("|")
        if len(fields) < 4:
            continue
        tres = _parse_tres(fields[1])
        try:
            elapsed = int(float(fields[2].strip() or 0))
        except ValueError:
            continue

        tasks += 1
        line_cpus = tres.get("cpu")
        line_gpus = _tres_gpus(tres)
        line_nodes = tres.get("node")

        # Per-task figures: take the largest seen. They are identical across
        # the tasks of an array, so this only matters when one line is missing
        # its TRES, which sacct does for a task that never started.
        if line_cpus is not None:
            cpus = max(cpus or 0, int(line_cpus))
        if line_gpus is not None:
            gpus = max(gpus or 0, int(line_gpus))
        if line_nodes is not None:
            nodes = max(nodes or 0, int(line_nodes))

        longest = max(longest or 0, elapsed)
        core_seconds += (line_cpus or 0) * elapsed
        gpu_seconds += (line_gpus or 0) * elapsed
        if fields[3].strip():
            codes.append(fields[3])

    if not tasks:
        return JobAccounting()

    return JobAccounting(
        cpus=cpus,
        gpus=gpus,
        nodes=nodes,
        runtime_seconds=longest,
        core_seconds=core_seconds if cpus is not None else None,
        gpu_seconds=gpu_seconds if gpus is not None else None,
        exit_code=_worst_exit_code(codes),
        tasks=tasks,
    )


async def job_accounting(host: str, user: str, job_id: str) -> JobAccounting:
    """What SLURM reserved for a finished job, empty when unavailable.

    Best-effort by design and never raises, for the same reasons as
    ``job_efficiency``: sacct needs the accounting database, which some sites
    do not run and DRAC login nodes intermittently cannot reach. An empty
    result is not a problem worth interrupting a notification for.

    Unlike ``seff`` this is asked about the array master and answers for every
    task at once, so the reserved core-hours it returns cover the whole array.
    """
    try:
        output = await run_remote(
            host, user,
            f"sacct -j {job_id} -n -X -o JobID,AllocTRES,ElapsedRaw,ExitCode "
            f"--parsable2 2>/dev/null",
        )
    except Exception:
        return JobAccounting()
    return _parse_accounting(output)
