"""Cluster probe: query sinfo, module avail, and sacctmgr; cache 24h.

Results are stored in ~/.cache/clusterpilot/<cluster_name>/probe.json and
returned from cache on subsequent calls until the TTL expires or force=True.

Parsed output is based on confirmed Grex (yak.hpc.umanitoba.ca) format.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from clusterpilot import paths
from clusterpilot.ssh.connection import SSHError, run_remote

# Resolved once at import. Set CLUSTERPILOT_HOME to relocate this, the config
# file, the job database and the systemd unit together (see paths.py).
_CACHE_ROOT = paths.cache_root()
_CACHE_TTL = 24 * 3600   # seconds


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PartitionInfo:
    name: str
    max_time: str    # e.g. "7-00:00:00" or "21-00:00:00"
    gres: str        # e.g. "gpu:v100:4" or "" for CPU-only
    nodes: int
    is_default: bool
    cpus: int = 0        # CPUs per node; 0 when the probe did not report it
    memory_mb: int = 0   # memory per node in MB; 0 when not reported


@dataclass
class ClusterProbe:
    cluster_name: str
    probed_at: float           # Unix timestamp
    partitions: list[PartitionInfo]
    julia_versions: list[str]  # e.g. ["julia/1.10.3", "julia/1.11.3"]
    accounts: list[str]        # e.g. ["def-stamps"]
    account_max_wall: dict[str, str]   # account → max walltime, "" = no limit
    python_versions: list[str] = field(default_factory=list)  # e.g. ["python/3.11.5"]
    scratch_env: str = ""      # value of $SCRATCH on the cluster, "" if unset

    def gpu_partitions(self) -> list[PartitionInfo]:
        """Return partitions that have GPU GRES."""
        return [p for p in self.partitions if p.gres.startswith("gpu:")]

    def cpu_partitions(self) -> list[PartitionInfo]:
        """Return CPU-only partitions."""
        return [p for p in self.partitions if not p.gres]

    def default_partition(self) -> PartitionInfo | None:
        for p in self.partitions:
            if p.is_default:
                return p
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def load_cache(cluster_name: str) -> ClusterProbe | None:
    """Return cached probe if it exists and is younger than 24h, else None."""
    path = _cache_path(cluster_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if time.time() - data["probed_at"] > _CACHE_TTL:
            return None
        return _from_dict(data)
    except (KeyError, ValueError):
        return None


def save_cache(probe: ClusterProbe) -> None:
    """Write probe data to ~/.cache/clusterpilot/<cluster>/probe.json."""
    path = _cache_path(probe.cluster_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(probe), indent=2))


async def probe_cluster(
    cluster_name: str,
    host: str,
    user: str,
    *,
    force: bool = False,
) -> ClusterProbe:
    """Query sinfo, module avail, and sacctmgr on host.

    Returns cached data if < 24h old (unless force=True).
    Saves fresh results to cache before returning.

    Requires an active SSH ControlMaster socket (call open_connection first).
    """
    if not force:
        cached = load_cache(cluster_name)
        if cached is not None:
            return cached

    sinfo_out, julia_out, python_out, sacctmgr_out, scratch_out = await _fetch_all(host, user)

    result = ClusterProbe(
        cluster_name=cluster_name,
        probed_at=time.time(),
        partitions=_parse_sinfo(sinfo_out),
        julia_versions=_parse_julia_modules(julia_out),
        python_versions=_parse_python_modules(python_out),
        accounts=_parse_accounts(sacctmgr_out),
        account_max_wall=_parse_max_wall(sacctmgr_out),
        scratch_env=scratch_out.strip(),
    )
    save_cache(result)
    return result


# ── Remote fetching ───────────────────────────────────────────────────────────

async def _fetch_all(host: str, user: str) -> tuple[str, str, str, str, str]:
    """Run all probe commands concurrently.

    Only ``sinfo`` is load-bearing for the partition picker; the other commands
    are best-effort. Empty results are returned for any of the auxiliary
    commands that fail (common on DRAC clusters where ``sacctmgr`` from the
    login node cannot reach ``slurmdbd``, or where the ``module`` system is
    unavailable). A failure of ``sinfo`` itself still raises.
    """
    sinfo_task = run_remote(host, user, "sinfo -o '%P %l %G %D %c %m' --noheader")
    julia_task = run_remote(host, user, "module avail julia 2>&1")
    python_task = run_remote(host, user, "module avail python 2>&1")
    sacctmgr_task = run_remote(
        host, user,
        f"sacctmgr show user {user} withassoc "
        f"format=account,maxjobs,maxwall -p --noheader",
    )
    scratch_task = run_remote(host, user, "echo $SCRATCH")

    results = await asyncio.gather(
        sinfo_task,
        julia_task,
        python_task,
        sacctmgr_task,
        scratch_task,
        return_exceptions=True,
    )

    sinfo_out = results[0]
    if isinstance(sinfo_out, BaseException):
        # No partitions means no submission, so surface this one.
        raise sinfo_out

    def _ok(value: object) -> str:
        return "" if isinstance(value, BaseException) else value  # type: ignore[return-value]

    return (
        sinfo_out,
        _ok(results[1]),
        _ok(results[2]),
        _ok(results[3]),
        _ok(results[4]),
    )


# ── Parsers ───────────────────────────────────────────────────────────────────

_LEADING_INT_RE = re.compile(r"^(\d+)")


def _leading_int(text: str) -> int:
    """First integer in a sinfo field, 0 when there is none.

    ``%c`` and ``%m`` are per-node figures, and a heterogeneous partition
    reports them as a range or an open-ended value: "32+", "16-32", "128000+".
    The smallest node is the one every task has to fit on, so the leading
    integer is the honest reading of all three forms.
    """
    match = _LEADING_INT_RE.match(text.strip())
    return int(match.group(1)) if match else 0


def _parse_sinfo(output: str) -> list[PartitionInfo]:
    """Parse `sinfo -o '%P %l %G %D %c %m' --noheader` output.

    Example line: "stamps 21-00:00:00 gpu:v100:4(S:0-1) 3 32 192000"

    Lines with only the first four fields are still read, so a probe cached
    before cores and memory were requested keeps working; the two missing
    figures come back as 0, which every caller treats as "not known".
    """
    partitions = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        name_raw, max_time, gres_raw, nodes_str = parts[0], parts[1], parts[2], parts[3]
        is_default = name_raw.endswith("*")
        name = name_raw.rstrip("*")
        # Strip socket-affinity suffix: "gpu:v100:4(S:0-1)" → "gpu:v100:4"
        gres = gres_raw.split("(")[0] if gres_raw != "(null)" else ""
        try:
            nodes = int(nodes_str)
        except ValueError:
            nodes = 0
        cpus = _leading_int(parts[4]) if len(parts) >= 6 else 0
        memory_mb = _leading_int(parts[5]) if len(parts) >= 6 else 0
        partitions.append(PartitionInfo(
            name=name,
            max_time=max_time,
            gres=gres,
            nodes=nodes,
            is_default=is_default,
            cpus=cpus,
            memory_mb=memory_mb,
        ))
    return partitions


def _parse_julia_modules(output: str) -> list[str]:
    """Extract julia/X.Y.Z tokens from `module avail julia 2>&1` output.

    Example: "   julia/1.10.3    julia/1.11.3 (D)"
    Tokens "(D)" are separate and filtered naturally by the startswith check.
    """
    versions: set[str] = set()
    for line in output.splitlines():
        for token in line.split():
            if token.startswith("julia/"):
                versions.add(token)
    return sorted(versions)


def _parse_python_modules(output: str) -> list[str]:
    """Extract python/X.Y.Z tokens from `module avail python 2>&1` output."""
    versions: set[str] = set()
    for line in output.splitlines():
        for token in line.split():
            if token.startswith("python/"):
                versions.add(token)
    return sorted(versions)


def _parse_accounts(output: str) -> list[str]:
    """Extract account names from pipe-delimited sacctmgr output."""
    accounts = []
    for line in output.splitlines():
        if "|" not in line:
            continue
        account = line.split("|")[0].strip()
        if account and account.lower() != "account":
            accounts.append(account)
    return accounts


def _parse_max_wall(output: str) -> dict[str, str]:
    """Extract account → max_walltime mapping from sacctmgr output.

    Empty string means no limit set at the account level.
    """
    result: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        account = parts[0].strip()
        max_wall = parts[2].strip()
        if account and account.lower() != "account":
            result[account] = max_wall
    return result


# ── Live availability (not cached) ────────────────────────────────────────────

@dataclass
class PartitionAvailability:
    idle: int    # fully unallocated nodes — jobs start immediately
    mix: int     # partially allocated nodes — also accept jobs if resources free
    total: int   # total nodes in the partition (across all states)
    state: str   # "up", "down", "drain", "inactive"

    @property
    def free(self) -> int:
        """Nodes able to accept a new job right now (idle + mix)."""
        return self.idle + self.mix


async def fetch_availability(host: str, user: str) -> dict[str, PartitionAvailability]:
    """Return partition → live availability. Not cached — always fresh.

    Uses ``sinfo -o '%P %D %t %a' --noheader`` which lists one row per
    (partition, node-state) combination so idle vs mix vs other can be
    counted separately. Aggregates across multiple rows for the same
    partition name (heterogeneous partitions can appear on many lines).
    """
    try:
        output = await run_remote(host, user, "sinfo -o '%P %D %t %a' --noheader")
        return _parse_availability(output)
    except Exception:
        return {}


# Trailing modifier characters that SLURM appends to node states:
# `*` not responding, `~` powered down, `#` powering up, `!` pending power down,
# `%` power saving, `@` pending reboot, `^` reboot complete, `-` maintenance.
_STATE_MODIFIERS = "*~#!%@^-"


def _parse_availability(output: str) -> dict[str, PartitionAvailability]:
    """Parse ``sinfo -o '%P %D %t %a' --noheader`` output.

    Each row has the form ``<partition> <node_count> <node_state> <partition_state>``.
    Idle and mix nodes both count as 'free' (they can accept a new job now);
    everything else (alloc, drain, drng, down, ...) contributes only to total.

    Example lines::

        stamps           4   idle   up
        gpubase_bynode_b1  1  mix    up
        gpubase_bynode_b1  3  drain* up
        gpubase_bynode_b1  132 drng  up
        gpubase_bynode_b1  5  drain  up
        lgpu             2   alloc  drain
    """
    aggregates: dict[str, dict] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        name = parts[0].rstrip("*")
        try:
            count = int(parts[1])
        except ValueError:
            continue
        # Strip trailing modifier chars before classifying the state.
        node_state = parts[2].lower().rstrip(_STATE_MODIFIERS)
        partition_state = parts[3].strip().lower()

        agg = aggregates.setdefault(
            name,
            {"idle": 0, "mix": 0, "total": 0, "state": partition_state},
        )
        if node_state == "idle":
            agg["idle"] += count
        elif node_state in ("mix", "mixed"):
            agg["mix"] += count
        agg["total"] += count
        # Non-up partition states propagate; up never overwrites down/drain.
        if partition_state != "up" and agg["state"] == "up":
            agg["state"] = partition_state

    return {
        name: PartitionAvailability(
            idle=a["idle"], mix=a["mix"], total=a["total"], state=a["state"]
        )
        for name, a in aggregates.items()
    }


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(cluster_name: str) -> Path:
    return _CACHE_ROOT / cluster_name / "probe.json"


def _partition_from_dict(raw: dict) -> PartitionInfo:
    """Rebuild one PartitionInfo from cached JSON, tolerating an older shape.

    A cache written before cores and memory were probed has neither key, so
    both default to 0 rather than making the whole cache unreadable.
    """
    return PartitionInfo(
        name=raw["name"],
        max_time=raw["max_time"],
        gres=raw["gres"],
        nodes=raw["nodes"],
        is_default=raw["is_default"],
        cpus=int(raw.get("cpus") or 0),
        memory_mb=int(raw.get("memory_mb") or 0),
    )


def _from_dict(data: dict) -> ClusterProbe:
    return ClusterProbe(
        cluster_name=data["cluster_name"],
        probed_at=data["probed_at"],
        partitions=[_partition_from_dict(p) for p in data["partitions"]],
        julia_versions=data["julia_versions"],
        python_versions=data.get("python_versions", []),   # backwards-compat
        accounts=data["accounts"],
        account_max_wall=data["account_max_wall"],
        scratch_env=data.get("scratch_env", ""),           # backwards-compat
    )
