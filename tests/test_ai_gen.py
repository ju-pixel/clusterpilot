"""Tests for jobs/ai_gen.py — system prompt construction (pure logic, no API calls)."""
from __future__ import annotations

import time

import pytest

from clusterpilot.cluster.probe import ClusterProbe, PartitionInfo
from clusterpilot.config import ClusterProfile
from clusterpilot.jobs.ai_gen import _build_system_prompt, _format_partitions


@pytest.fixture
def grex_probe():
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


@pytest.fixture
def grex_profile():
    return ClusterProfile(
        name="grex",
        host="yak.hpc.umanitoba.ca",
        user="juliaf",
        account="def-stamps",
        scratch="$HOME/clusterpilot_jobs",
    )


# ── _format_partitions ────────────────────────────────────────────────────────

class TestFormatPartitions:
    def test_gpu_partition_shows_gres(self, grex_probe):
        result = _format_partitions(grex_probe)
        assert "gpu:v100:4" in result

    def test_cpu_partition_shows_cpu_only(self, grex_probe):
        result = _format_partitions(grex_probe)
        assert "(CPU only)" in result

    def test_all_partition_names_present(self, grex_probe):
        result = _format_partitions(grex_probe)
        for name in ("skylake", "stamps", "lgpu", "largemem"):
            assert name in result

    def test_default_partition_marked(self, grex_probe):
        result = _format_partitions(grex_probe)
        assert "[DEFAULT]" in result

    def test_non_default_partition_not_marked(self, grex_probe):
        probe = ClusterProbe(
            cluster_name="grex", probed_at=time.time(),
            partitions=[PartitionInfo("stamps", "21-00:00:00", "gpu:v100:4", 3, is_default=False)],
            julia_versions=[], accounts=[], account_max_wall={},
        )
        result = _format_partitions(probe)
        assert "[DEFAULT]" not in result


# ── _build_system_prompt ──────────────────────────────────────────────────────

class TestBuildSystemPrompt:
    def test_contains_cluster_name(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile)
        assert "grex" in prompt

    def test_contains_host(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile)
        assert "yak.hpc.umanitoba.ca" in prompt

    def test_contains_julia_versions(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile)
        assert "julia/1.10.3" in prompt
        assert "julia/1.11.3" in prompt

    def test_contains_account(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile)
        assert "def-stamps" in prompt

    def test_contains_expanded_scratch_path(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile)
        # $HOME should be expanded in the prompt
        assert "$HOME" not in prompt

    def test_starts_with_bash_instruction(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile)
        assert "#!/bin/bash" in prompt

    def test_output_only_instruction_present(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile)
        assert "Output ONLY the bash script" in prompt

    def test_falls_back_to_probe_account_when_profile_account_empty(self, grex_probe):
        profile_no_account = ClusterProfile(
            name="grex",
            host="yak.hpc.umanitoba.ca",
            user="juliaf",
            account="",   # no account in profile
            scratch="$HOME/clusterpilot_jobs",
        )
        prompt = _build_system_prompt(grex_probe, profile_no_account)
        # Should fall back to probe.accounts[0]
        assert "def-stamps" in prompt

    def test_falls_back_to_default_julia_when_none_found(self, grex_profile):
        probe_no_julia = ClusterProbe(
            cluster_name="grex", probed_at=time.time(),
            partitions=[],
            julia_versions=[],   # nothing found
            accounts=["def-stamps"],
            account_max_wall={},
        )
        prompt = _build_system_prompt(probe_no_julia, grex_profile)
        assert "julia/1.11.3" in prompt   # hard-coded fallback

    def test_output_log_format_uses_percent_x_j(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile)
        assert "%x-%j.out" in prompt
