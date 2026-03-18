"""Cluster probe: query sinfo, module avail, and sacctmgr; cache 24h.

Results are stored in ~/.cache/clusterpilot/<cluster_name>/probe.json and
returned from cache on subsequent calls until the TTL expires or force=True.

Parsed output is based on confirmed Grex (yak.hpc.umanitoba.ca) format.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from clusterpilot.ssh.connection import run_remote

_CACHE_ROOT = Path.home() / ".cache" / "clusterpilot"
_CACHE_TTL = 24 * 3600   # seconds


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PartitionInfo:
    name: str
    max_time: str    # e.g. "7-00:00:00" or "21-00:00:00"
    gres: str        # e.g. "gpu:v100:4" or "" for CPU-only
    nodes: int
    is_default: bool


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
    """Run all probe commands concurrently."""
    return await asyncio.gather(
        run_remote(host, user, "sinfo -o '%P %l %G %D' --noheader"),
        run_remote(host, user, "module avail julia 2>&1"),
        run_remote(host, user, "module avail python 2>&1"),
        run_remote(
            host, user,
            f"sacctmgr show user {user} withassoc "
            f"format=account,maxjobs,maxwall -p --noheader",
        ),
        run_remote(host, user, "echo $SCRATCH"),
    )


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_sinfo(output: str) -> list[PartitionInfo]:
    """Parse `sinfo -o '%P %l %G %D' --noheader` output.

    Example line: "stamps 21-00:00:00 gpu:v100:4(S:0-1) 3"
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
        partitions.append(PartitionInfo(
            name=name,
            max_time=max_time,
            gres=gres,
            nodes=nodes,
            is_default=is_default,
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
    idle: int
    total: int
    state: str   # "up", "down", "drain", "inactive"


async def fetch_availability(host: str, user: str) -> dict[str, PartitionAvailability]:
    """Return partition → live availability. Not cached — always fresh.

    Uses ``sinfo -o '%P %F %a' --noheader`` which reports
    Allocated/Idle/Other/Total node counts and partition state per row.
    Aggregates across multiple rows for the same partition name
    (heterogeneous partitions can appear on more than one line).
    """
    try:
        output = await run_remote(host, user, "sinfo -o '%P %F %a' --noheader")
        return _parse_availability(output)
    except Exception:
        return {}


def _parse_availability(output: str) -> dict[str, PartitionAvailability]:
    """Parse ``sinfo -o '%P %F %a' --noheader`` output.

    Example lines::

        stamps   2/1/0/8   up
        stamps-b 0/0/3/3   drain
        skylake  10/20/0/40 up
        lgpu     0/0/2/2   down
    """
    result: dict[str, PartitionAvailability] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[0].rstrip("*")
        state = parts[2].strip() if len(parts) >= 3 else "up"
        try:
            counts = parts[1].split("/")
            if len(counts) >= 4:
                idle_val = int(counts[1])
                total_val = int(counts[3])
            elif len(counts) >= 2:
                # Fallback: A/I only (older SLURM)
                idle_val = int(counts[1])
                total_val = int(counts[0]) + idle_val
            else:
                continue
        except (ValueError, IndexError):
            continue

        if name in result:
            existing = result[name]
            # For state: propagate non-up states; drain/down take priority over up.
            merged_state = state if existing.state == "up" else existing.state
            result[name] = PartitionAvailability(
                idle=existing.idle + idle_val,
                total=existing.total + total_val,
                state=merged_state,
            )
        else:
            result[name] = PartitionAvailability(
                idle=idle_val, total=total_val, state=state
            )
    return result


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(cluster_name: str) -> Path:
    return _CACHE_ROOT / cluster_name / "probe.json"


def _from_dict(data: dict) -> ClusterProbe:
    return ClusterProbe(
        cluster_name=data["cluster_name"],
        probed_at=data["probed_at"],
        partitions=[PartitionInfo(**p) for p in data["partitions"]],
        julia_versions=data["julia_versions"],
        python_versions=data.get("python_versions", []),   # backwards-compat
        accounts=data["accounts"],
        account_max_wall=data["account_max_wall"],
        scratch_env=data.get("scratch_env", ""),           # backwards-compat
    )
