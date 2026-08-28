"""Deterministic checks on a generated SLURM script, run before submit.

Nothing between generation and ``sbatch`` inspects the script today:
``clusterpilot.tui.submit._sanitise_script`` rewrites ``--output`` and strips
absolute job-directory prefixes, and that is the whole of it. This module fills
the gap. It compares what the user asked for against what the generator
actually emitted, and returns typed findings.

The validator carries NO cluster knowledge. Every cluster fact it uses arrives
as an argument: walltime limits come from the probe (``PartitionInfo``), and
everything else comes from the user's own submit fields (``SubmitIntent``).
Where a check could only be made by building in per-cluster knowledge (queue
walltime buckets, a site's GPU naming rules), the check is deliberately absent
rather than guessed at. Note that despite its name ``cluster/slurm.py`` holds
no cluster-specific branching at all: the DRAC and Grex quirks live in
``jobs/ai_gen.py`` and ``jobs/preflight.py``. This module deliberately depends
on none of them.

It also never chooses a partition. It may check the partition the user picked
for consistency with the emitted script, and that is all.

A malformed script produces FINDINGS, never exceptions. An exception from this
module means programmer error, such as an impossible ``SubmitIntent``.

Checks implemented, by slug:

``shebang``                 the script starts with a ``#!`` line
``bash-syntax``             ``bash -n`` accepts the script
``miscased-directive``      a ``#sbatch`` line SLURM would silently ignore
``array-mismatch``          the emitted ``--array`` disagrees with the intent
``array-missing``           an array was asked for but none was emitted
``gpu-count``               a multi-GPU request on a single-task job
``walltime-over-partition`` ``--time`` exceeds the probed partition limit
``driver-not-uploaded``     the script runs a file the upload set omits
``truncated``               the generation looks cut off part way through
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from clusterpilot.cluster.probe import PartitionInfo

# Seconds allowed for the `bash -n` subprocess before the check is skipped.
_BASH_TIMEOUT_SECONDS = 10.0

# Longest offending line quoted back in a finding's message.
_QUOTE_LIMIT = 80


# ── Errors ────────────────────────────────────────────────────────────────────

class IntentError(ValueError):
    """Raised when the validator is handed an unusable ``SubmitIntent``.

    This is programmer error on the calling side, not a defect in the script
    under validation. A bad script yields findings instead.
    """


# ── Data classes ──────────────────────────────────────────────────────────────

class Severity(Enum):
    """How seriously a finding should be taken."""

    BLOCKING = "BLOCKING"
    WARNING = "WARNING"

    @property
    def rank(self) -> int:
        """Sort key, lowest first, so blocking findings surface at the top."""
        return 0 if self is Severity.BLOCKING else 1


@dataclass(frozen=True)
class Finding:
    """One problem found in a generated script.

    ``check`` is a stable slug so a caller can offer a per-check override
    without matching on prose. ``line`` is the 1-based line number in the
    script when the problem can be pinned to one, otherwise None.
    """

    check: str
    severity: Severity
    message: str
    line: int | None = None


@dataclass(frozen=True)
class SubmitIntent:
    """What the user actually asked for on the submit screen.

    Every field is the user's own input, never a cluster fact:

    ``array_spec``          the ARRAY field, verbatim, "" when left blank
    ``param_row_count``     rows in the parameter table, None when there is none
    ``driver_rel``          driver path relative to the project root
    ``upload_paths``        paths queued for upload, rsync include patterns
                            allowed; empty means the upload set is unknown
    ``partition_name``      the partition the user picked, never one we chose
    ``requested_walltime``  the walltime the user asked for, for the caller's
                            intended-against-emitted diff
    """

    array_spec: str = ""
    param_row_count: int | None = None
    driver_rel: str = ""
    upload_paths: Sequence[str] = ()
    partition_name: str = ""
    requested_walltime: str = ""


# ── Public API ────────────────────────────────────────────────────────────────

def validate_script(
    script: str,
    *,
    intent: SubmitIntent,
    partitions: Sequence[PartitionInfo] | None = None,
) -> list[Finding]:
    """Check *script* against *intent* and return every finding, worst first.

    *partitions* is the probed partition table for the selected cluster. Omit
    it and the checks that need probed facts are skipped rather than guessed.

    Raises ``IntentError`` when *intent* itself is impossible.
    """
    _require_valid_intent(intent)

    findings: list[Finding] = []
    findings.extend(_check_shebang(script))
    findings.extend(_check_bash_syntax(script))
    findings.extend(_check_miscased_directives(script))
    findings.extend(_check_array(script, intent))
    findings.extend(_check_gpu_count(script))
    findings.extend(_check_walltime(script, intent, partitions))
    findings.extend(_check_driver_uploaded(script, intent))
    findings.extend(_check_truncated(script))
    return findings


def blocking(findings: Sequence[Finding]) -> bool:
    """True when at least one finding should stop the submit."""
    return any(f.severity is Severity.BLOCKING for f in findings)


def format_findings(findings: Sequence[Finding]) -> str:
    """Render findings for a terminal panel, one line each, most severe first.

    Findings of equal severity keep the order they were produced in. Returns
    an empty string when there is nothing to report, so a caller can hide the
    panel outright.
    """
    lines: list[str] = []
    for finding in sorted(findings, key=lambda f: f.severity.rank):
        where = f" (line {finding.line})" if finding.line is not None else ""
        message = " ".join(finding.message.split())
        lines.append(f"{finding.severity.value:<8}  {finding.check}{where}: {message}")
    return "\n".join(lines)


# ── Intent validation ─────────────────────────────────────────────────────────

def _require_valid_intent(intent: SubmitIntent) -> None:
    """Raise ``IntentError`` when the caller built an impossible intent."""
    if not isinstance(intent, SubmitIntent):
        raise IntentError(f"intent must be a SubmitIntent, got {type(intent).__name__}")
    count = intent.param_row_count
    if count is None:
        return
    if isinstance(count, bool) or not isinstance(count, int):
        raise IntentError(
            f"param_row_count must be an int or None, got {type(count).__name__}"
        )
    if count < 1:
        raise IntentError(f"param_row_count must be at least 1, got {count}")


# ── Directive parsing ─────────────────────────────────────────────────────────

def _directive_lines(script: str) -> Iterator[tuple[int, str]]:
    """Yield (line number, directive body) for every line SLURM honours.

    Only exactly-cased ``#SBATCH`` at the very start of a line counts, because
    that is all SLURM reads. A mis-cased or indented line is a plain comment,
    so the resource it names is genuinely absent from the job.
    """
    for number, line in enumerate(script.splitlines(), start=1):
        if not line.startswith("#SBATCH"):
            continue
        rest = line[len("#SBATCH"):]
        if rest and not rest[0].isspace():
            continue
        yield number, rest.strip()


def _directive_value(script: str, option: str) -> tuple[int, str] | None:
    """Return (line number, value) for the last ``--option`` given, or None.

    SLURM lets a later directive override an earlier one, so the last wins.
    Both ``--option=value`` and ``--option value`` are read.
    """
    pattern = re.compile(rf"(?:^|\s)--{re.escape(option)}(?:=|\s+)(\S+)")
    result: tuple[int, str] | None = None
    for number, body in _directive_lines(script):
        match = pattern.search(body)
        if match:
            result = (number, match.group(1))
    return result


def _quote(text: str) -> str:
    """Shorten a line for quoting back inside a finding message."""
    stripped = text.strip()
    if len(stripped) <= _QUOTE_LIMIT:
        return stripped
    return stripped[:_QUOTE_LIMIT] + "..."


# ── Check: shebang ────────────────────────────────────────────────────────────

def _check_shebang(script: str) -> list[Finding]:
    """The first line must be a ``#!`` interpreter line.

    A shebang anywhere later does not count: the kernel only reads the first
    two bytes of the file, so the job would run under whatever shell SLURM
    falls back to.
    """
    if script.startswith("#!"):
        return []
    return [
        Finding(
            check="shebang",
            severity=Severity.BLOCKING,
            message=(
                "The script does not start with a #! line. Without one the job runs "
                "under whatever shell SLURM falls back to, which is rarely the shell "
                "the script was written for."
            ),
            line=1,
        )
    ]


# ── Check: bash syntax ────────────────────────────────────────────────────────

def _check_bash_syntax(
    script: str,
    *,
    timeout: float = _BASH_TIMEOUT_SECONDS,
) -> list[Finding]:
    """Run ``bash -n`` over the script text and report a genuine failure.

    The check is skipped, with no finding, when bash is not installed or the
    subprocess cannot be run at all: an absent tool is not evidence of a bad
    script.
    """
    bash = shutil.which("bash")
    if bash is None:
        return []

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", prefix="clusterpilot_validate_", delete=False
        ) as handle:
            tmp_path = handle.name
            handle.write(script)
        completed = subprocess.run(
            [bash, "-n", tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        # Could not run the check at all, so there is nothing to report.
        return []
    finally:
        if tmp_path is not None:
            Path(tmp_path).unlink(missing_ok=True)

    if completed.returncode == 0:
        return []

    detail = _first_message_line(completed.stderr)
    if tmp_path is not None:
        detail = detail.replace(tmp_path, "the script")
    match = re.search(r"line (\d+)", detail)
    return [
        Finding(
            check="bash-syntax",
            severity=Severity.BLOCKING,
            message=f"bash -n rejected the script: {detail}",
            line=int(match.group(1)) if match else None,
        )
    ]


def _first_message_line(stderr: str) -> str:
    """First non-empty line of bash's complaint, or a neutral fallback."""
    for line in stderr.splitlines():
        if line.strip():
            return line.strip()
    return "bash reported a syntax error but said nothing further."


# ── Check: mis-cased directives ───────────────────────────────────────────────

_MISCASED_RE = re.compile(r"^#sbatch\b", re.IGNORECASE)


def _check_miscased_directives(script: str) -> list[Finding]:
    """Report ``#sbatch`` lines that SLURM will silently ignore.

    SLURM reads only the uppercase ``#SBATCH``. Anything else is an ordinary
    comment, so the resource the line asks for vanishes without a word at
    submit time and the job starts short of what it needed.
    """
    findings: list[Finding] = []
    for number, line in enumerate(script.splitlines(), start=1):
        if line.startswith("#SBATCH"):
            continue
        if not _MISCASED_RE.match(line):
            continue
        findings.append(
            Finding(
                check="miscased-directive",
                severity=Severity.BLOCKING,
                message=(
                    f"'{_quote(line)}' is not spelled #SBATCH, so SLURM reads it as a "
                    "plain comment and the resource it asks for is silently dropped."
                ),
                line=number,
            )
        )
    return findings


# ── Check: job array ──────────────────────────────────────────────────────────

def _count_array_tasks(spec: str) -> int | None:
    """Number of tasks a SLURM array spec covers, or None if unparseable.

    Handles ``a``, ``a-b``, ``a-b:step`` and comma-separated lists of those,
    with an optional trailing ``%limit`` (a concurrency cap, which does not
    change how many tasks run).
    """
    body = spec.split("%", 1)[0].strip()
    if not body:
        return None

    total = 0
    for raw_item in body.split(","):
        item = raw_item.strip()
        if not item:
            return None
        step = 1
        if ":" in item:
            item, _, step_text = item.partition(":")
            if not step_text.isdigit() or int(step_text) == 0:
                return None
            step = int(step_text)
        if "-" in item:
            start_text, _, end_text = item.partition("-")
            if not (start_text.isdigit() and end_text.isdigit()):
                return None
            start, end = int(start_text), int(end_text)
            if end < start:
                return None
            total += (end - start) // step + 1
        else:
            if not item.isdigit() or step != 1:
                return None
            total += 1
    return total


def _check_array(script: str, intent: SubmitIntent) -> list[Finding]:
    """Compare the emitted ``--array`` against what the user asked for.

    An explicit ARRAY field wins: the emitted spec must equal it, so an
    explicit subset of a longer parameter table stays possible. With no ARRAY
    field, the emitted spec must cover exactly one task per table row.
    """
    emitted = _directive_value(script, "array")
    wanted = intent.array_spec.strip()
    rows = intent.param_row_count

    if emitted is None:
        if wanted:
            return [
                Finding(
                    check="array-missing",
                    severity=Severity.BLOCKING,
                    message=(
                        f"An array of '{wanted}' was asked for but the script emits no "
                        "--array directive, so it would run as a single job."
                    ),
                )
            ]
        if rows is None:
            return []
        return [
            Finding(
                check="array-mismatch",
                severity=Severity.BLOCKING,
                message=(
                    f"The parameter table has {rows} rows but the script emits no "
                    "--array directive, so only one task would run."
                ),
            )
        ]

    line, spec = emitted

    if wanted:
        if spec == wanted:
            return []
        return [
            Finding(
                check="array-mismatch",
                severity=Severity.BLOCKING,
                message=(
                    f"The script emits --array={spec} but the submit form asked for "
                    f"{wanted}."
                ),
                line=line,
            )
        ]

    if rows is None:
        return []

    count = _count_array_tasks(spec)
    if count is None:
        return [
            Finding(
                check="array-mismatch",
                severity=Severity.BLOCKING,
                message=(
                    f"The emitted array spec '{spec}' could not be read, so it cannot be "
                    f"matched against the {rows}-row parameter table."
                ),
                line=line,
            )
        ]
    if count != rows:
        return [
            Finding(
                check="array-mismatch",
                severity=Severity.BLOCKING,
                message=(
                    f"The script emits --array={spec}, which covers {count} task(s), but "
                    f"the parameter table has {rows} rows."
                ),
                line=line,
            )
        ]
    return []


# ── Check: GPU count ──────────────────────────────────────────────────────────

def _gpu_requests(script: str) -> list[tuple[int, int, str]]:
    """Every GPU request in the script as (line number, count, text).

    Reads the two forms the generator produces, ``--gpus=[type:]N`` and
    ``--gres=gpu[:type][:N]``. A GRES entry with no count means one GPU.
    """
    requests: list[tuple[int, int, str]] = []
    gpus_re = re.compile(r"(?:^|\s)--gpus=(\S+)")
    gres_re = re.compile(r"(?:^|\s)--gres=(\S+)")

    for number, body in _directive_lines(script):
        match = gpus_re.search(body)
        if match:
            count = _count_gpu_value(match.group(1))
            if count is not None:
                requests.append((number, count, f"--gpus={match.group(1)}"))
        match = gres_re.search(body)
        if match:
            count = _count_gres_gpus(match.group(1))
            if count is not None:
                requests.append((number, count, f"--gres={match.group(1)}"))
    return requests


def _count_gpu_value(value: str) -> int | None:
    """Total GPUs named by a ``--gpus`` value such as ``2`` or ``a100:2``."""
    total = 0
    for item in value.split(","):
        fields = item.split(":")
        tail = fields[-1]
        if tail.isdigit():
            total += int(tail)
        elif len(fields) == 1 and item:
            total += 1
        else:
            return None
    return total or None


def _count_gres_gpus(value: str) -> int | None:
    """Total GPUs named by a ``--gres`` value, ignoring non-GPU resources."""
    total = 0
    seen_gpu = False
    for item in value.split(","):
        fields = item.split(":")
        if not fields or fields[0] != "gpu":
            continue
        seen_gpu = True
        tail = fields[-1]
        total += int(tail) if tail.isdigit() else 1
    return total if seen_gpu else None


def _is_single_task(script: str) -> bool:
    """True when the script asks for one task on one node.

    Absent directives count as one, matching SLURM's own defaults. An array
    job is still single-task by this measure: every array element is its own
    one-task job, which is exactly the case a copied node inventory spoils.
    """
    for option in ("ntasks", "ntasks-per-node", "nodes"):
        found = _directive_value(script, option)
        if found is None:
            continue
        try:
            if int(found[1]) > 1:
                return False
        except ValueError:
            # An unreadable count means we cannot tell, so stay quiet.
            return False

    short_re = re.compile(r"(?:^|\s)-[nN]\s*(\d+)")
    for _, body in _directive_lines(script):
        match = short_re.search(body)
        if match and int(match.group(1)) > 1:
            return False
    return True


def _check_gpu_count(script: str) -> list[Finding]:
    """Warn when a single-task job asks for more than one GPU.

    That shape is usually the partition's whole-node inventory copied into a
    per-task request. Genuinely multi-GPU jobs exist, so this warns and never
    blocks.
    """
    if not _is_single_task(script):
        return []
    findings: list[Finding] = []
    for number, count, text in _gpu_requests(script):
        if count <= 1:
            continue
        findings.append(
            Finding(
                check="gpu-count",
                severity=Severity.WARNING,
                message=(
                    f"'{text}' asks for {count} GPUs on a single-task job. That is often "
                    "the partition's whole-node inventory copied into a per-task "
                    "request. Ignore this if the job really does use them all."
                ),
                line=number,
            )
        )
    return findings


# ── Check: walltime against the probed partition limit ────────────────────────

def _parse_walltime_seconds(text: str) -> int | None:
    """Seconds in a SLURM walltime string, or None when it cannot be read.

    Accepts ``minutes``, ``MM:SS``, ``HH:MM:SS``, ``D-HH``, ``D-HH:MM`` and
    ``D-HH:MM:SS``. Anything else, including ``infinite`` and an empty limit,
    returns None so the caller skips the comparison instead of guessing.
    """
    value = text.strip()
    if not value:
        return None

    days = 0
    has_days = "-" in value
    if has_days:
        day_text, _, value = value.partition("-")
        if not day_text.isdigit():
            return None
        days = int(day_text)

    parts = value.split(":")
    if not 1 <= len(parts) <= 3 or any(not p.isdigit() for p in parts):
        return None
    numbers = [int(p) for p in parts]

    if has_days:
        hours = numbers[0]
        minutes = numbers[1] if len(numbers) > 1 else 0
        seconds = numbers[2] if len(numbers) > 2 else 0
    elif len(numbers) == 1:
        hours, minutes, seconds = 0, numbers[0], 0
    elif len(numbers) == 2:
        hours, minutes, seconds = 0, numbers[0], numbers[1]
    else:
        hours, minutes, seconds = numbers

    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _check_walltime(
    script: str,
    intent: SubmitIntent,
    partitions: Sequence[PartitionInfo] | None,
) -> list[Finding]:
    """Compare the emitted ``--time`` with the probed limit of the chosen partition.

    The limit is a probed fact, never a built-in one, so the check is skipped
    whenever the partition table is absent, the user picked no partition, the
    named partition is not in the table, or either walltime cannot be read.
    The partition is only ever checked, never chosen.
    """
    if not partitions:
        return []
    name = intent.partition_name.strip()
    if not name:
        return []
    chosen = next((p for p in partitions if p.name == name), None)
    if chosen is None:
        return []
    limit = _parse_walltime_seconds(chosen.max_time)
    if limit is None:
        return []

    emitted = _directive_value(script, "time")
    if emitted is None:
        return []
    line, value = emitted
    requested = _parse_walltime_seconds(value)
    if requested is None or requested <= limit:
        return []

    return [
        Finding(
            check="walltime-over-partition",
            severity=Severity.BLOCKING,
            message=(
                f"The script asks for --time={value} but the probed limit of partition "
                f"'{name}' is {chosen.max_time}, so sbatch will refuse the job."
            ),
            line=line,
        )
    ]


# ── Check: the driver is in the upload set ────────────────────────────────────

def _normalise_path(path: str) -> str:
    """Strip ``./`` prefixes, leading and trailing slashes, and whitespace."""
    text = path.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def _find_invocation(script: str, driver: str) -> int | None:
    """Line number where the script clearly runs *driver*, or None.

    Deliberately conservative: only an unindented-or-indented executable line
    counts, comments are ignored, and the path must appear as a whole token so
    that ``other/scripts/run.jl`` never matches ``scripts/run.jl``.
    """
    candidates = {driver, f"./{driver}"}
    patterns = [
        re.compile(rf"(?<![\w./\\-]){re.escape(c)}(?![\w.\\-])")
        for c in candidates
    ]
    for number, line in enumerate(script.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        for pattern in patterns:
            if pattern.search(line):
                return number
    return None


def _is_uploaded(driver: str, upload_paths: Sequence[str]) -> bool:
    """True when some upload entry covers *driver*.

    An entry may name the file itself or a directory containing it, with or
    without an rsync wildcard tail such as ``src/***``.
    """
    target = _normalise_path(driver)
    if not target:
        return False
    for raw in upload_paths:
        entry = _normalise_path(raw).rstrip("*").strip("/")
        if not entry:
            continue
        if entry == target or target.startswith(entry + "/"):
            return True
    return False


def _check_driver_uploaded(script: str, intent: SubmitIntent) -> list[Finding]:
    """Report a driver the script runs but the upload set leaves behind.

    Skipped when no driver was named or the upload set is empty, since an
    unknown upload set proves nothing about the driver.
    """
    driver = intent.driver_rel.strip()
    if not driver:
        return []
    uploads = [p for p in intent.upload_paths if p and p.strip()]
    if not uploads:
        return []
    line = _find_invocation(script, driver)
    if line is None:
        return []
    if _is_uploaded(driver, uploads):
        return []
    return [
        Finding(
            check="driver-not-uploaded",
            severity=Severity.BLOCKING,
            message=(
                f"The script runs '{driver}' but no upload entry covers that path, so "
                "the job would die as soon as it started, having burnt its queue wait."
            ),
            line=line,
        )
    ]


# ── Check: truncated generation ───────────────────────────────────────────────

def _has_unterminated_quote(script: str) -> bool:
    """True when the script ends inside a quoted string.

    A small shell-quoting state machine: single quotes take everything
    literally, double quotes honour a backslash escape, and an unquoted ``#``
    at the start of a word opens a comment.
    """
    quote = ""
    in_comment = False
    previous = ""
    for char in script:
        if in_comment:
            if char == "\n":
                in_comment = False
            previous = char
            continue
        if quote == "'":
            if char == "'":
                quote = ""
            previous = char
            continue
        if quote == '"':
            if previous == "\\":
                previous = ""
                continue
            if char == '"':
                quote = ""
            previous = char
            continue
        if previous == "\\":
            previous = ""
            continue
        if char in ("'", '"'):
            quote = char
        elif char == "#" and (previous == "" or previous.isspace()):
            in_comment = True
        previous = char
    return quote != ""


_CUT_TAIL_RE = re.compile(r"(\\|\||&&|\|\||&)$")


def _check_truncated(script: str) -> list[Finding]:
    """Warn when the generation looks as though it stopped part way through.

    This is a heuristic, and it is stated as one in the finding it produces.
    A missing trailing newline is the necessary condition, since a complete
    generation almost always ends in one. On its own that is not enough, so a
    finding also needs a second signal: the script ending inside a quote, a
    final line ending on a continuation or a shell operator, or a final
    ``#SBATCH`` line with nothing after its ``=``. A tidy script that merely
    lacks its last newline therefore produces nothing.
    """
    if not script or script.endswith("\n"):
        return []
    lines = script.splitlines()
    if not lines:
        return []
    last = lines[-1].rstrip()
    line_number = len(lines)

    reasons: list[str] = []
    if _has_unterminated_quote(script):
        reasons.append("it ends inside an unterminated quote")
    if _CUT_TAIL_RE.search(last):
        reasons.append("the last line ends on a continuation or a shell operator")
    if last.startswith("#SBATCH") and (last.endswith("=") or last.strip() == "#SBATCH"):
        reasons.append("the last line is an #SBATCH directive with no value")

    if not reasons:
        return []
    return [
        Finding(
            check="truncated",
            severity=Severity.WARNING,
            message=(
                "The script may have been cut off before it finished: it has no trailing "
                f"newline and {reasons[0]}. This is a heuristic, so check the end of the "
                "script yourself before submitting."
            ),
            line=line_number,
        )
    ]
