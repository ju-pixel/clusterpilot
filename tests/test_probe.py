"""Tests for cluster/probe.py — parsers and cache round-trip."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from clusterpilot.cluster.probe import (
    ClusterProbe,
    PartitionInfo,
    _parse_accounts,
    _parse_availability,
    _parse_julia_modules,
    _parse_max_wall,
    _parse_sinfo,
    load_cache,
    probe_cluster,
    save_cache,
)
from clusterpilot.ssh.connection import SSHError


# ── _parse_sinfo ───────────────────────────────────────────────────────────────

class TestParseSinfo:
    def test_gpu_partition_with_socket_affinity(self):
        output = "stamps 21-00:00:00 gpu:v100:4(S:0-1) 3"
        result = _parse_sinfo(output)
        assert len(result) == 1
        p = result[0]
        assert p.name == "stamps"
        assert p.max_time == "21-00:00:00"
        assert p.gres == "gpu:v100:4"
        assert p.nodes == 3
        assert p.is_default is False

    def test_default_partition_marker_stripped(self):
        output = "skylake* 7-00:00:00 (null) 10"
        result = _parse_sinfo(output)
        assert result[0].name == "skylake"
        assert result[0].is_default is True
        assert result[0].gres == ""

    def test_cpu_only_partition(self):
        output = "largemem 14-00:00:00 (null) 4"
        result = _parse_sinfo(output)
        assert result[0].gres == ""
        assert result[0].nodes == 4

    def test_multiple_partitions(self):
        output = (
            "skylake* 7-00:00:00 (null) 10\n"
            "stamps 21-00:00:00 gpu:v100:4(S:0-1) 3\n"
            "lgpu 3-00:00:00 gpu:l40s:2 2"
        )
        result = _parse_sinfo(output)
        assert len(result) == 3
        names = [p.name for p in result]
        assert names == ["skylake", "stamps", "lgpu"]

    def test_short_line_skipped(self):
        output = "bad line\nskylake* 7-00:00:00 (null) 10"
        result = _parse_sinfo(output)
        assert len(result) == 1
        assert result[0].name == "skylake"

    def test_invalid_node_count_defaults_to_zero(self):
        output = "test 1:00:00 (null) N/A"
        result = _parse_sinfo(output)
        assert result[0].nodes == 0

    def test_empty_output(self):
        assert _parse_sinfo("") == []

    def test_gpu_without_socket_affinity(self):
        output = "gpu 7-00:00:00 gpu:v100:4 2"
        result = _parse_sinfo(output)
        assert result[0].gres == "gpu:v100:4"


# ── _parse_julia_modules ──────────────────────────────────────────────────────

class TestParseJuliaModules:
    def test_typical_lmod_output(self):
        output = "   julia/1.10.3    julia/1.11.3 (D)   "
        result = _parse_julia_modules(output)
        assert "julia/1.10.3" in result
        assert "julia/1.11.3" in result
        assert "(D)" not in result

    def test_deduplication(self):
        output = "julia/1.10.3\njulia/1.10.3\njulia/1.11.3"
        result = _parse_julia_modules(output)
        assert result.count("julia/1.10.3") == 1

    def test_sorted_output(self):
        output = "julia/1.11.3 julia/1.10.3"
        result = _parse_julia_modules(output)
        assert result == sorted(result)

    def test_no_julia_modules(self):
        output = "No modules found matching 'julia'"
        assert _parse_julia_modules(output) == []

    def test_empty_output(self):
        assert _parse_julia_modules("") == []


# ── _parse_accounts ───────────────────────────────────────────────────────────

class TestParseAccounts:
    def test_typical_sacctmgr_output(self):
        output = "def-stamps|10|7-00:00:00|\ndef-other|5||\n"
        result = _parse_accounts(output)
        assert "def-stamps" in result
        assert "def-other" in result

    def test_header_line_filtered(self):
        output = "Account|MaxJobs|MaxWall|\ndef-stamps|10|7-00:00:00|"
        result = _parse_accounts(output)
        assert "Account" not in result
        assert "def-stamps" in result

    def test_lines_without_pipe_skipped(self):
        output = "no pipes here\ndef-stamps|10|7-00:00:00|"
        result = _parse_accounts(output)
        assert len(result) == 1

    def test_empty_output(self):
        assert _parse_accounts("") == []


# ── _parse_max_wall ───────────────────────────────────────────────────────────

class TestParseMaxWall:
    def test_with_wall_limit(self):
        output = "def-stamps|10|7-00:00:00|\n"
        result = _parse_max_wall(output)
        assert result["def-stamps"] == "7-00:00:00"

    def test_no_wall_limit(self):
        output = "def-stamps|10||\n"
        result = _parse_max_wall(output)
        assert result["def-stamps"] == ""

    def test_multiple_accounts(self):
        output = "def-stamps|10|7-00:00:00|\ndef-other|5|3-00:00:00|"
        result = _parse_max_wall(output)
        assert result["def-stamps"] == "7-00:00:00"
        assert result["def-other"] == "3-00:00:00"

    def test_short_lines_skipped(self):
        output = "bad\ndef-stamps|10|7-00:00:00|"
        result = _parse_max_wall(output)
        assert "def-stamps" in result
        assert len(result) == 1

    def test_empty_output(self):
        assert _parse_max_wall("") == {}


# ── ClusterProbe methods ──────────────────────────────────────────────────────

class TestClusterProbeMethods:
    @pytest.fixture
    def probe(self):
        return ClusterProbe(
            cluster_name="grex",
            probed_at=time.time(),
            partitions=[
                PartitionInfo("skylake", "7-00:00:00", "", 10, is_default=True),
                PartitionInfo("stamps", "21-00:00:00", "gpu:v100:4", 3, is_default=False),
                PartitionInfo("lgpu", "3-00:00:00", "gpu:l40s:2", 2, is_default=False),
                PartitionInfo("largemem", "14-00:00:00", "", 4, is_default=False),
            ],
            julia_versions=["julia/1.10.3", "julia/1.11.3"],
            accounts=["def-stamps"],
            account_max_wall={"def-stamps": "7-00:00:00"},
        )

    def test_gpu_partitions(self, probe):
        gpu = probe.gpu_partitions()
        assert len(gpu) == 2
        assert all(p.gres.startswith("gpu:") for p in gpu)

    def test_cpu_partitions(self, probe):
        cpu = probe.cpu_partitions()
        assert len(cpu) == 2
        assert all(not p.gres for p in cpu)

    def test_default_partition(self, probe):
        default = probe.default_partition()
        assert default is not None
        assert default.name == "skylake"

    def test_default_partition_none_when_absent(self):
        probe = ClusterProbe(
            cluster_name="test", probed_at=0.0,
            partitions=[PartitionInfo("x", "1:00:00", "", 1, is_default=False)],
            julia_versions=[], accounts=[], account_max_wall={},
        )
        assert probe.default_partition() is None


# ── Cache round-trip ──────────────────────────────────────────────────────────

class TestCache:
    @pytest.fixture
    def probe(self):
        return ClusterProbe(
            cluster_name="grex",
            probed_at=time.time(),
            partitions=[
                PartitionInfo("skylake", "7-00:00:00", "", 10, is_default=True),
            ],
            julia_versions=["julia/1.11.3"],
            accounts=["def-stamps"],
            account_max_wall={"def-stamps": "7-00:00:00"},
        )

    def test_save_and_load_roundtrip(self, probe, tmp_path):
        with patch("clusterpilot.cluster.probe._CACHE_ROOT", tmp_path):
            save_cache(probe)
            loaded = load_cache("grex")
        assert loaded is not None
        assert loaded.cluster_name == "grex"
        assert loaded.partitions[0].name == "skylake"
        assert loaded.julia_versions == ["julia/1.11.3"]

    def test_load_returns_none_when_missing(self, tmp_path):
        with patch("clusterpilot.cluster.probe._CACHE_ROOT", tmp_path):
            result = load_cache("grex")
        assert result is None

    def test_load_returns_none_when_expired(self, probe, tmp_path):
        probe.probed_at = time.time() - (25 * 3600)  # 25h ago
        with patch("clusterpilot.cluster.probe._CACHE_ROOT", tmp_path):
            save_cache(probe)
            result = load_cache("grex")
        assert result is None

    def test_load_returns_none_on_corrupt_json(self, tmp_path):
        cache_dir = tmp_path / "grex"
        cache_dir.mkdir(parents=True)
        (cache_dir / "probe.json").write_text("not valid json{{")
        with patch("clusterpilot.cluster.probe._CACHE_ROOT", tmp_path):
            result = load_cache("grex")
        assert result is None


# ── _parse_availability (per-state aggregation) ───────────────────────────────

class TestParseAvailability:
    """Backed by ``sinfo -o '%P %D %t %a' --noheader`` which yields one row per
    (partition, node-state) combination. The parser must aggregate across rows
    and classify idle and mix nodes separately from everything else.
    """

    def test_single_partition_all_idle(self):
        result = _parse_availability("stamps 4 idle up")
        pa = result["stamps"]
        assert pa.idle == 4 and pa.mix == 0 and pa.total == 4
        assert pa.state == "up"
        assert pa.free == 4

    def test_narval_busy_with_mix_and_drained(self):
        """Narval gpubase_bynode_b1: 1 mix, 3 drain*, 132 drng, 5 drain."""
        output = (
            "gpubase_bynode_b1 1 mix up\n"
            "gpubase_bynode_b1 3 drain* up\n"
            "gpubase_bynode_b1 132 drng up\n"
            "gpubase_bynode_b1 5 drain up\n"
        )
        pa = _parse_availability(output)["gpubase_bynode_b1"]
        assert pa.idle == 0
        assert pa.mix == 1
        assert pa.total == 141
        assert pa.state == "up"
        assert pa.free == 1

    def test_state_modifier_suffix_stripped(self):
        """`mix-`, `drain*`, `idle~` should be classified by their base state."""
        output = (
            "p1 2 mix- up\n"
            "p1 1 idle~ up\n"
            "p1 3 alloc up\n"
        )
        pa = _parse_availability(output)["p1"]
        assert pa.mix == 2
        assert pa.idle == 1
        assert pa.total == 6

    def test_partition_state_drain_propagates(self):
        """If any row reports the partition as drain/down, that wins over up."""
        output = (
            "lgpu 1 alloc up\n"
            "lgpu 1 idle drain\n"
        )
        assert _parse_availability(output)["lgpu"].state == "drain"

    def test_up_state_does_not_overwrite_drain(self):
        output = (
            "lgpu 1 alloc drain\n"
            "lgpu 1 idle up\n"
        )
        assert _parse_availability(output)["lgpu"].state == "drain"

    def test_mixed_partition_with_idle_and_mix(self):
        output = (
            "skylake 2 idle up\n"
            "skylake 3 mix up\n"
            "skylake 5 alloc up\n"
        )
        pa = _parse_availability(output)["skylake"]
        assert pa.idle == 2
        assert pa.mix == 3
        assert pa.total == 10
        assert pa.free == 5

    def test_default_partition_star_stripped(self):
        result = _parse_availability("skylake* 4 idle up")
        assert "skylake" in result
        assert "skylake*" not in result

    def test_short_or_malformed_lines_ignored(self):
        output = (
            "stamps 4 idle up\n"
            "\n"
            "incomplete row\n"
            "stamps nodecount idle up\n"   # non-integer count
            "stamps-b 2 mix up\n"
        )
        result = _parse_availability(output)
        assert result["stamps"].total == 4
        assert result["stamps-b"].total == 2

    def test_empty_output(self):
        assert _parse_availability("") == {}


# ── Probe resilience to auxiliary command failures ────────────────────────────

class TestProbeResilience:
    """Auxiliary probe commands (sacctmgr, module avail, $SCRATCH) often fail on
    DRAC login nodes — sacctmgr cannot reach slurmdbd from Narval/Cedar login
    nodes. The probe must still succeed if sinfo works, so the partition picker
    can be populated. Only a sinfo failure is fatal.
    """

    SINFO_OUT = "stamps 21-00:00:00 gpu:v100:4 3\nskylake* 7-00:00:00 (null) 10"

    @pytest.mark.asyncio
    async def test_probe_succeeds_when_sacctmgr_fails(self, tmp_path):
        """Mirrors the Narval failure: sacctmgr raises, the rest succeed."""

        async def fake_run_remote(host, user, cmd, **kwargs):
            if cmd.startswith("sinfo"):
                return self.SINFO_OUT
            if cmd.startswith("sacctmgr"):
                raise SSHError(
                    "Remote command failed (exit 1): sacctmgr ... "
                    "_open_persist_conn: failed to open persistent connection "
                    "to host:nvl-slurmdb:6819: Connection refused"
                )
            if cmd.startswith("module avail julia"):
                return "julia/1.11.3"
            if cmd.startswith("module avail python"):
                return "python/3.11.5"
            if cmd.startswith("echo $SCRATCH"):
                return "/scratch/juliaf"
            raise AssertionError(f"Unexpected command: {cmd!r}")

        with patch("clusterpilot.cluster.probe._CACHE_ROOT", tmp_path), \
             patch("clusterpilot.cluster.probe.run_remote", new=fake_run_remote):
            probe = await probe_cluster("narval", "narval.alliancecan.ca", "juliaf")

        # Partition picker can populate.
        assert [p.name for p in probe.partitions] == ["stamps", "skylake"]
        # Auxiliary results degrade gracefully.
        assert probe.accounts == []
        assert probe.account_max_wall == {}
        # The other auxiliaries that did succeed should still come through.
        assert probe.julia_versions == ["julia/1.11.3"]
        assert probe.python_versions == ["python/3.11.5"]
        assert probe.scratch_env == "/scratch/juliaf"

    @pytest.mark.asyncio
    async def test_probe_raises_when_sinfo_fails(self, tmp_path):
        """sinfo is load-bearing: if it fails we cannot populate partitions."""

        async def fake_run_remote(host, user, cmd, **kwargs):
            if cmd.startswith("sinfo"):
                raise SSHError("Remote command failed (exit 255): sinfo ...")
            return ""

        with patch("clusterpilot.cluster.probe._CACHE_ROOT", tmp_path), \
             patch("clusterpilot.cluster.probe.run_remote", new=fake_run_remote):
            with pytest.raises(SSHError):
                await probe_cluster("narval", "narval.alliancecan.ca", "juliaf")

    @pytest.mark.asyncio
    async def test_probe_survives_module_and_scratch_failures(self, tmp_path):
        """Generic clusters may not have `module` or $SCRATCH at all."""

        async def fake_run_remote(host, user, cmd, **kwargs):
            if cmd.startswith("sinfo"):
                return self.SINFO_OUT
            if cmd.startswith("sacctmgr"):
                return "def-stamps|10|7-00:00:00|"
            # Module system absent, $SCRATCH unset.
            raise SSHError(f"Remote command failed (exit 127): {cmd}")

        with patch("clusterpilot.cluster.probe._CACHE_ROOT", tmp_path), \
             patch("clusterpilot.cluster.probe.run_remote", new=fake_run_remote):
            probe = await probe_cluster("generic", "host.example", "user")

        assert len(probe.partitions) == 2
        assert probe.accounts == ["def-stamps"]
        assert probe.julia_versions == []
        assert probe.python_versions == []
        assert probe.scratch_env == ""
