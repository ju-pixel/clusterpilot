"""Parameter tables: one row per array task, columns become environment variables.

A parameter table is the structured alternative to describing an array's
index-to-parameter mapping in prose. The user supplies a CSV or TSV whose header
names the variables and whose rows are the tasks:

    lattice   eta    samples
    fcc       0.30   512
    bcc       0.15   512

ClusterPilot uploads the file alongside the driver, derives the array size from
the row count, and the generated script reads row ``$SLURM_ARRAY_TASK_ID`` and
exports each column. The read loop comes from :func:`render_bash_reader` so its
shape is fixed rather than reinvented by a language model on every generation.

Pure parsing and rendering. No subprocess calls, no cluster knowledge, and
nothing here selects a partition or infers a resource request.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

# A column header becomes a shell variable name verbatim, so it must be a valid
# identifier. Leading digits and hyphens are the common spreadsheet mistakes.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Headers that would collide with something the job script or SLURM already owns.
_RESERVED_HEADERS = frozenset({
    "PATH", "HOME", "USER", "SHELL", "PWD", "LD_PRELOAD", "LD_LIBRARY_PATH",
    "SLURM_ARRAY_TASK_ID", "SLURM_JOB_ID", "SLURM_ARRAY_JOB_ID",
})

_DELIMITERS = {".csv": ",", ".tsv": "\t", ".tab": "\t"}


class ParamsTableError(Exception):
    """Raised when a parameter table cannot be parsed or is not usable."""


@dataclass(frozen=True)
class ParamsTable:
    """A parsed parameter table.

    Attributes:
        path:    The table's path as given, for messages and the upload set.
        headers: Column names, in file order. Each is a valid shell identifier.
        rows:    One list of cell values per task, aligned to ``headers``.
    """

    path: Path
    headers: list[str]
    rows: list[list[str]]

    @property
    def task_count(self) -> int:
        """Number of array tasks this table defines."""
        return len(self.rows)

    @property
    def array_spec(self) -> str:
        """The array spec this table implies, zero-indexed to match task ids."""
        return f"0-{self.task_count - 1}"

    def row_for(self, task_id: int) -> dict[str, str]:
        """Return one task's parameters as a mapping, for a fallback manifest.

        Raises:
            ParamsTableError: if ``task_id`` is outside the table.
        """
        if not 0 <= task_id < self.task_count:
            raise ParamsTableError(
                f"task id {task_id} is outside the table, which has "
                f"{self.task_count} rows (0 to {self.task_count - 1})"
            )
        return dict(zip(self.headers, self.rows[task_id]))


# ── Public API ────────────────────────────────────────────────────────────────

def load_params_table(path: str | Path) -> ParamsTable:
    """Parse a parameter table from a CSV or TSV file.

    The delimiter is chosen from the file extension: ``.csv`` is comma
    separated, ``.tsv`` and ``.tab`` are tab separated. Blank lines are ignored
    so a trailing newline does not become an empty task.

    Raises:
        ParamsTableError: if the file is missing, unreadable, has an unknown
            extension, is empty, has a malformed header, or has rows whose width
            does not match the header.
    """
    table_path = Path(path)
    delimiter = _DELIMITERS.get(table_path.suffix.lower())
    if delimiter is None:
        raise ParamsTableError(
            f"{table_path.name}: unsupported extension "
            f"'{table_path.suffix}'. Use .csv or .tsv"
        )

    try:
        text = table_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParamsTableError(f"cannot read {table_path}: {exc}") from exc

    records = [
        row for row in csv.reader(text.splitlines(), delimiter=delimiter)
        if any(cell.strip() for cell in row)
    ]
    if not records:
        raise ParamsTableError(f"{table_path.name} is empty")

    headers = [cell.strip() for cell in records[0]]
    _validate_headers(headers, table_path.name)

    rows: list[list[str]] = []
    for offset, record in enumerate(records[1:], start=2):
        cells = [cell.strip() for cell in record]
        if len(cells) != len(headers):
            raise ParamsTableError(
                f"{table_path.name} line {offset}: expected "
                f"{len(headers)} values to match the header, found {len(cells)}"
            )
        rows.append(cells)

    if not rows:
        raise ParamsTableError(
            f"{table_path.name} has a header but no data rows, so it defines "
            "no tasks"
        )
    return ParamsTable(path=table_path, headers=headers, rows=rows)


def render_bash_reader(table: ParamsTable, *, indent: str = "") -> str:
    """Render the bash that reads this task's row and exports its columns.

    The generated script includes this verbatim. Keeping it here, rather than
    asking the model to write it, means the mapping from array index to
    parameters has exactly one implementation.

    The reader is zero-indexed on ``SLURM_ARRAY_TASK_ID`` and skips the header,
    so task 0 is the first data row. It fails loudly on a missing file or an
    out-of-range index, because a task that silently runs with empty parameters
    is worse than one that does not start.
    """
    name = table.path.name
    delimiter = _DELIMITERS[table.path.suffix.lower()]
    awk_fs = "," if delimiter == "," else "\\t"
    assignments = "\n".join(
        f'{indent}export {header}="$(echo "$_cp_row" | cut -d"{delimiter}" -f{i})"'
        if delimiter == ","
        else f'{indent}export {header}="$(echo "$_cp_row" | cut -f{i})"'
        for i, header in enumerate(table.headers, start=1)
    )
    return (
        f'{indent}# Parameter table: one row per array task, written by ClusterPilot.\n'
        f'{indent}_cp_table="{name}"\n'
        f'{indent}if [ ! -f "$_cp_table" ]; then\n'
        f'{indent}    echo "ERROR: parameter table $_cp_table not found" >&2\n'
        f'{indent}    exit 1\n'
        f'{indent}fi\n'
        f'{indent}_cp_row="$(awk -F\'{awk_fs}\' -v n="$SLURM_ARRAY_TASK_ID" '
        f'\'NR==n+2\' "$_cp_table")"\n'
        f'{indent}if [ -z "$_cp_row" ]; then\n'
        f'{indent}    echo "ERROR: no row for SLURM_ARRAY_TASK_ID=$SLURM_ARRAY_TASK_ID '
        f'in $_cp_table" >&2\n'
        f'{indent}    exit 1\n'
        f'{indent}fi\n'
        f"{assignments}\n"
    )


def describe_for_prompt(table: ParamsTable) -> str:
    """A short description of the table for the script-generation prompt.

    Gives the model the header and the task count so it can reason about the
    job, without asking it to reproduce the rows. The rows stay in the uploaded
    file, which is the single source of truth.
    """
    return (
        f"A parameter table '{table.path.name}' with {table.task_count} data "
        f"rows will be uploaded beside the driver. Its columns are: "
        f"{', '.join(table.headers)}. One row is one array task."
    )


# ── Internals ─────────────────────────────────────────────────────────────────

def _validate_headers(headers: list[str], filename: str) -> None:
    """Raise if any header is unusable as a shell variable name."""
    if not headers:
        raise ParamsTableError(f"{filename}: the header row is empty")

    for header in headers:
        if not header:
            raise ParamsTableError(
                f"{filename}: the header row has a blank column name"
            )
        if not _IDENTIFIER.match(header):
            raise ParamsTableError(
                f"{filename}: column name '{header}' is not a valid shell "
                "identifier. Use letters, digits and underscores, not starting "
                "with a digit"
            )
        if header.upper() in _RESERVED_HEADERS:
            raise ParamsTableError(
                f"{filename}: column name '{header}' would overwrite an "
                "environment variable the job depends on. Rename it"
            )

    duplicates = sorted({h for h in headers if headers.count(h) > 1})
    if duplicates:
        raise ParamsTableError(
            f"{filename}: duplicate column name(s): {', '.join(duplicates)}"
        )
