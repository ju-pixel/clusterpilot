"""Tests for jobs/ai_gen.py — system prompt construction (pure logic, no API calls)."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from clusterpilot.cluster.probe import ClusterProbe, PartitionInfo
from clusterpilot.config import ClusterProfile
from clusterpilot.jobs.ai_gen import (
    ApiUsage,
    _build_system_prompt,
    _format_partitions,
    _one_gpu_of,
    estimate_cost,
    price_for,
)


def gpu_block(prompt: str) -> str:
    """The GPU REQUIRED section only, "" when the prompt has none.

    The partition table lists every GRES the probe found, so a bare
    ``"gpu:a100:4" in prompt`` says nothing about the directive the AI is told
    to emit. These tests read the block itself.
    """
    marker = "═══ GPU REQUIRED ═══"
    if marker not in prompt:
        return ""
    return prompt.split(marker, 1)[1].split("═══", 1)[0]


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
        # The job directory is shown in ~ form for the remote shell; the
        # workstation's own home path must never leak into the prompt (#17).
        # "$HOME" itself may appear in the storage advice, so it is not banned.
        prompt = _build_system_prompt(grex_probe, grex_profile)
        assert "Job working directory: ~/clusterpilot_jobs/<job-name>/" in prompt
        assert str(Path.home()) not in prompt

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
            account="",
            scratch="$HOME/clusterpilot_jobs",
        )
        prompt = _build_system_prompt(grex_probe, profile_no_account)
        assert "def-stamps" in prompt

    def test_falls_back_to_default_julia_when_none_found(self, grex_profile):
        probe_no_julia = ClusterProbe(
            cluster_name="grex", probed_at=time.time(),
            partitions=[],
            julia_versions=[],
            accounts=["def-stamps"],
            account_max_wall={},
        )
        prompt = _build_system_prompt(probe_no_julia, grex_profile)
        assert "julia/1.11.3" in prompt

    def test_output_log_format_uses_percent_x_j(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile)
        assert "%x-%j.out" in prompt

    def test_partition_hard_constraint_when_specified(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile, partition="stamps")
        assert "--partition=stamps" in prompt
        assert "MUST" in prompt

    def test_no_partition_constraint_when_empty(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile, partition="")
        assert "MUST" not in prompt

    def test_script_content_included_when_provided(self, grex_probe, grex_profile):
        content = 'using CUDA\nusing Flux\nprintln("train")'
        prompt = _build_system_prompt(grex_probe, grex_profile, script_content=content)
        assert "using CUDA" in prompt
        assert "USER'S SCRIPT" in prompt

    def test_no_script_section_when_content_none(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile, script_content=None)
        assert "USER'S SCRIPT" not in prompt


# ── Fieldnotes run manifest nudge (opt-in) ────────────────────────────────────

class TestFieldnotesManifestNudge:
    def test_absent_by_default(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile)
        assert "params.json" not in prompt
        assert "Fieldnotes run manifest" not in prompt

    def test_absent_when_disabled(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile, fieldnotes_enabled=False)
        assert "params.json" not in prompt

    def test_present_when_enabled(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile, fieldnotes_enabled=True)
        assert "params.json" in prompt
        assert "Fieldnotes run manifest" in prompt
        # Explicitly distinguished from the dependency manifest concept.
        assert "unrelated to the dependency manifest" in prompt


# ── DRAC behaviour: partition is a routing hint, not a hard --partition= ──────

@pytest.fixture
def narval_probe():
    return ClusterProbe(
        cluster_name="narval",
        probed_at=time.time(),
        partitions=[
            PartitionInfo("gpubase_interac", "8:00:00", "gpu:a100_4g.20gb:1", 89, is_default=False),
            PartitionInfo("gpubase_bynode_b3", "1-00:00:00", "gpu:a100:4", 141, is_default=False),
            PartitionInfo("cpubase_bycore_b3", "1-00:00:00", "", 20, is_default=False),
        ],
        julia_versions=["julia/1.11.3"],
        accounts=["def-stamps"],
        account_max_wall={"def-stamps": ""},
        scratch_env="/scratch/juliaf",
    )


@pytest.fixture
def narval_profile():
    return ClusterProfile(
        name="narval",
        host="narval.alliancecan.ca",
        user="juliaf",
        account="def-stamps",
        scratch="$SCRATCH/clusterpilot_jobs",
        cluster_type="drac",
    )


class TestDracPartitionHandling:
    """Mirrors the Narval failure from 2026-05-21: sbatch rejected the job
    because ClusterPilot pinned --partition=gpubase_interac on a DRAC cluster
    where the scheduler routes by --gres instead. On DRAC, the picked partition
    must become a GRES / walltime hint, never a hard --partition= directive.
    """

    def test_no_partition_directive_in_rules(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3"
        )
        # The "Always include these #SBATCH directives" block must not list
        # --partition. The DRAC scheduling note above may still reference the
        # string `--partition=` in its prohibition, so we check the directive
        # row marker specifically.
        assert "   --partition      " not in prompt

    def test_no_hard_partition_must_rule(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3"
        )
        # On Grex/generic the rule contains "MUST use exactly `--partition=X`";
        # on DRAC that string must not appear.
        assert "MUST use exactly `--partition=" not in prompt

    def test_drac_scheduling_note_present(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3"
        )
        assert "DRAC SCHEDULING" in prompt
        assert "DO NOT emit" in prompt
        assert "--gres" in prompt

    def test_picked_partition_becomes_gpu_type_hint(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3"
        )
        # The GPU TYPE of gpubase_bynode_b3 is the hint. Its count (4) is the
        # node's whole inventory and must not be handed over as a target (#8).
        assert "GPU type on this partition: a100" in prompt
        assert "match this exactly" not in prompt
        assert "gpubase_bynode_b3" in prompt

    def test_walltime_ceiling_surfaced(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_interac"
        )
        # max_time on gpubase_interac is 8 hours — must be surfaced so the AI
        # respects it when generating --time.
        assert "8:00:00" in prompt

    def test_cpu_partition_pick_has_no_gres_hint(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="cpubase_bycore_b3"
        )
        assert "CPU-only" in prompt
        assert "do not emit --gres" in prompt.lower()

    def test_grex_behaviour_unchanged(self, grex_probe, grex_profile):
        """Sanity check: my DRAC branch must not affect non-DRAC clusters.
        grex_profile defaults to cluster_type='generic'.
        """
        prompt = _build_system_prompt(grex_probe, grex_profile, partition="stamps")
        assert "--partition=stamps" in prompt
        assert "MUST" in prompt
        assert "DRAC SCHEDULING" not in prompt


class TestDracOfflineJuliaEnv:
    """On DRAC the depot is pre-warmed on the login node by
    clusterpilot.jobs.preflight, so the compute-node script must set
    JULIA_PKG_OFFLINE=true to skip the registry network update that fails
    on a no-internet compute node (Narval 2026-05-21 incident).
    """

    def _julia_manifest_env(self):
        from clusterpilot.jobs.env_detect import ScriptEnvironment
        return ScriptEnvironment(
            language="julia",
            has_manifest=True,
            third_party_imports=[],
            driver_extension=".jl",
        )

    def test_drac_julia_env_has_offline_flag(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3",
            script_env=self._julia_manifest_env(),
        )
        assert "JULIA_PKG_OFFLINE=true" in prompt
        # The instantiate command must be gone (#10): preflight already ran it
        # on the login node and the compute node has no internet, so an
        # in-script call can only stall on the registry update or fail. Only
        # the prohibition may name Pkg.instantiate(), never an instruction to
        # emit it.
        assert "julia --project=. -e 'import Pkg; Pkg.instantiate()'" not in prompt
        assert "Do NOT run Pkg.instantiate() or Pkg.add()" in prompt
        assert "instantiated on the login node" in prompt

    def test_grex_julia_env_has_no_offline_flag(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(
            grex_probe, grex_profile, partition="stamps",
            script_env=self._julia_manifest_env(),
        )
        assert "JULIA_PKG_OFFLINE" not in prompt
        assert "Pkg.instantiate()" in prompt

    def test_drac_julia_inferred_imports_also_offline(self, narval_probe, narval_profile):
        from clusterpilot.jobs.env_detect import ScriptEnvironment
        env = ScriptEnvironment(
            language="julia",
            has_manifest=False,
            third_party_imports=["CUDA", "Flux"],
            driver_extension=".jl",
        )
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3",
            script_env=env,
        )
        assert "JULIA_PKG_OFFLINE=true" in prompt
        # Inferred imports take the same no-Pkg path on DRAC (#10).
        assert 'Pkg.add(["CUDA", "Flux"])' not in prompt
        assert "Pkg.instantiate()'" not in prompt
        assert "Do NOT run Pkg.instantiate() or Pkg.add()" in prompt
        assert "instantiated on the login node" in prompt

    def test_grex_julia_inferred_imports_keep_pkg_add(self, grex_probe, grex_profile):
        """Only DRAC drops the Pkg calls: Grex compute nodes have internet."""
        from clusterpilot.jobs.env_detect import ScriptEnvironment
        env = ScriptEnvironment(
            language="julia",
            has_manifest=False,
            third_party_imports=["CUDA", "Flux"],
            driver_extension=".jl",
        )
        prompt = _build_system_prompt(
            grex_probe, grex_profile, partition="stamps", script_env=env,
        )
        assert 'Pkg.add(["CUDA", "Flux"])' in prompt
        assert "Pkg.instantiate()" in prompt


class TestGpuDirectiveBlock:
    """Without an explicit --gres, the DRAC routing layer puts the job on a CPU
    node and `CUDA.device()` fails with 'CUDA driver not functional' (Narval
    2026-05-21 job 61344777). When the driver imports a GPU library, the
    prompt must contain a hard imperative to emit --gres in the SBATCH block.
    """

    def _env(self, imports):
        from clusterpilot.jobs.env_detect import ScriptEnvironment
        return ScriptEnvironment(
            language="julia",
            has_manifest=True,
            third_party_imports=imports,
            driver_extension=".jl",
        )

    def test_cuda_import_triggers_gpu_block(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3",
            script_env=self._env(["CUDA", "JLD2", "Random"]),
        )
        assert "GPU REQUIRED" in prompt
        assert "MUST emit" in prompt
        assert "--gres=" in prompt

    def test_drac_asks_for_one_gpu_of_the_partition_type(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3",
            script_env=self._env(["CUDA"]),
        )
        # The picked partition's gres is "gpu:a100:4": the type seeds the
        # default, the node's inventory count does not (#8).
        block = gpu_block(prompt)
        assert "--gres=gpu:a100:1" in block
        assert "gpu:a100:4" not in block

    def test_drac_no_picked_partition_falls_back_to_one_untyped_gpu(
        self, narval_probe, narval_profile
    ):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="",
            script_env=self._env(["CUDA"]),
        )
        # No partition means no known type, so no model may be invented (#28).
        block = gpu_block(prompt)
        assert "--gres=gpu:1" in block
        assert "a100" not in block

    def test_python_torch_also_triggers(self, narval_probe, narval_profile):
        from clusterpilot.jobs.env_detect import ScriptEnvironment
        env = ScriptEnvironment(
            language="python",
            has_manifest=True,
            third_party_imports=["torch", "numpy"],
            driver_extension=".py",
        )
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3",
            script_env=env,
        )
        assert "GPU REQUIRED" in prompt
        assert "torch" in prompt

    def test_no_gpu_imports_no_block(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3",
            script_env=self._env(["JLD2", "Random", "Statistics"]),
        )
        assert "GPU REQUIRED" not in prompt

    def test_no_script_env_no_block(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3",
        )
        assert "GPU REQUIRED" not in prompt


class TestGrexGresTypeless:
    """Grex's submit_filter.lua rejects --gres=gpu:<type>:<count> on some
    partitions (lgpu in particular): it expands the partition list to include
    the user's default CPU partition and errors out with 'lgpu is meant for
    GPU jobs only' (UManitoba Grex 2026-05-21). Bare --gres=gpu:N is the safe
    default; the AI should only emit the type subspec when the user explicitly
    asks for a specific GPU type.
    """

    @pytest.fixture
    def grex_drac_aware_profile(self):
        """Grex profile with cluster_type explicitly 'grex' (the default fixture is 'generic')."""
        return ClusterProfile(
            name="grex",
            host="yak.hpc.umanitoba.ca",
            user="juliaf",
            account="def-stamps",
            scratch="$HOME/clusterpilot_jobs",
            cluster_type="grex",
        )

    def _cuda_env(self):
        from clusterpilot.jobs.env_detect import ScriptEnvironment
        return ScriptEnvironment(
            language="julia",
            has_manifest=True,
            third_party_imports=["CUDA"],
            driver_extension=".jl",
        )

    def test_grex_gpu_directive_uses_typeless_gres(self, grex_probe, grex_drac_aware_profile):
        prompt = _build_system_prompt(
            grex_probe, grex_drac_aware_profile, partition="lgpu",
            script_env=self._cuda_env(),
        )
        # The MUST-emit line defaults to gpu:1 on Grex.
        assert "--gres=gpu:1" in prompt
        # The type subspec is NOT recommended as the default.
        assert "--gres=gpu:l40s:1" not in prompt
        assert "--gres=gpu:v100:" not in prompt

    def test_grex_directive_explains_when_to_use_type(self, grex_probe, grex_drac_aware_profile):
        prompt = _build_system_prompt(
            grex_probe, grex_drac_aware_profile, partition="lgpu",
            script_env=self._cuda_env(),
        )
        # The directive must tell the AI to only add type when user explicitly asks.
        assert "type-less form" in prompt
        assert "explicitly" in prompt
        assert "lgpu" in prompt

    def test_grex_rule_2_uses_typeless_form(self, grex_probe, grex_drac_aware_profile):
        """Even when no GPU library is in imports, rule 2's guidance should be type-less on Grex."""
        prompt = _build_system_prompt(
            grex_probe, grex_drac_aware_profile, partition="stamps",
        )
        # Rule 2's example is the type-less form on Grex.
        assert "gpu:<count>" in prompt
        # It must still mention that type subspec exists for explicit user request.
        assert "gpu:v100:N" in prompt or "type subspec" in prompt

    def test_drac_still_uses_the_partition_gpu_type(self, narval_probe, narval_profile):
        """DRAC keeps the typed form: one GPU of the picked partition's type."""
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3",
            script_env=self._cuda_env(),
        )
        assert "--gres=gpu:a100:1" in gpu_block(prompt)
        # DRAC should NOT get the Grex-specific note.
        assert "type-less form" not in prompt

    def test_generic_cluster_unchanged(self, grex_probe, grex_profile):
        """grex_profile defaults to cluster_type='generic' — original behaviour."""
        prompt = _build_system_prompt(
            grex_probe, grex_profile, partition="stamps",
            script_env=self._cuda_env(),
        )
        # Generic falls back to the placeholder syntax (rule 2 example).
        assert "gpu:<type>:<count>" in prompt


class TestOneGpuOf:
    """One GPU of a partition's type, never the node's whole inventory (#8)."""

    def test_whole_card_keeps_its_type(self):
        assert _one_gpu_of("gpu:a100:4") == "gpu:a100:1"

    def test_mig_slice_keeps_its_type(self):
        assert _one_gpu_of("gpu:a100_3g.20gb:3") == "gpu:a100_3g.20gb:1"

    def test_empty_gres_stays_empty(self):
        assert _one_gpu_of("") == ""

    def test_non_gpu_gres_stays_empty(self):
        assert _one_gpu_of("mps:100") == ""

    def test_typeless_gres_drops_the_count(self):
        assert _one_gpu_of("gpu:4") == "gpu:1"


class TestGpuSizeChoice:
    """The GPU SIZE picker on F2 is a hard constraint on every cluster type.

    A MIG slice ("a100_3g.20gb") and a whole card ("a100") are different
    resources to SLURM, so the choice has to reach the directive verbatim.
    """

    def _cuda_env(self):
        from clusterpilot.jobs.env_detect import ScriptEnvironment
        return ScriptEnvironment(
            language="julia",
            has_manifest=True,
            third_party_imports=["CUDA"],
            driver_extension=".jl",
        )

    @pytest.fixture
    def grex_typed_profile(self):
        return ClusterProfile(
            name="grex",
            host="yak.hpc.umanitoba.ca",
            user="juliaf",
            account="def-stamps",
            scratch="$HOME/clusterpilot_jobs",
            cluster_type="grex",
        )

    def test_drac_slice_choice_wins_over_the_partition_type(
        self, narval_probe, narval_profile
    ):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3",
            gpu_size="a100_3g.20gb",
            script_env=self._cuda_env(),
        )
        block = gpu_block(prompt)
        assert "--gres=gpu:a100_3g.20gb:1" in block
        assert "gpu:a100:4" not in block
        assert "--gres=gpu:a100:1" not in block

    def test_the_choice_is_quoted_back_as_the_user_s_own(
        self, narval_probe, narval_profile
    ):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3",
            gpu_size="a100_3g.20gb",
            script_env=self._cuda_env(),
        )
        assert "chose `a100_3g.20gb` on the submit screen" in gpu_block(prompt)

    def test_grex_honours_the_choice(self, grex_probe, grex_typed_profile):
        prompt = _build_system_prompt(
            grex_probe, grex_typed_profile, partition="lgpu",
            gpu_size="l40s",
            script_env=self._cuda_env(),
        )
        assert "--gres=gpu:l40s:1" in gpu_block(prompt)

    def test_grex_without_a_choice_stays_type_less(self, grex_probe, grex_typed_profile):
        prompt = _build_system_prompt(
            grex_probe, grex_typed_profile, partition="lgpu",
            script_env=self._cuda_env(),
        )
        block = gpu_block(prompt)
        assert "--gres=gpu:1" in block
        assert "--gres=gpu:l40s:1" not in block

    def test_generic_honours_the_choice(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(
            grex_probe, grex_profile, partition="stamps",
            gpu_size="v100",
            script_env=self._cuda_env(),
        )
        block = gpu_block(prompt)
        assert "--gres=gpu:v100:1" in block
        assert "gpu:<type>:<count>" not in block

    def test_no_gpu_import_no_block_at_all(self, narval_probe, narval_profile):
        """A GPU size on a CPU job changes nothing: there is no GPU block."""
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3",
            gpu_size="a100",
        )
        assert gpu_block(prompt) == ""


class TestDracCudacoreDirective:
    """On DRAC, CUDA.jl needs libcuda.so on LD_LIBRARY_PATH at runtime. The
    cudacore module provides it. ClusterPilot's preflight separately writes
    LocalPreferences.toml; the AI must add the `module load cudacore` line.
    """

    def _cuda_env(self):
        from clusterpilot.jobs.env_detect import ScriptEnvironment
        return ScriptEnvironment(
            language="julia",
            has_manifest=True,
            third_party_imports=["CUDA"],
            driver_extension=".jl",
        )

    def _no_cuda_env(self):
        from clusterpilot.jobs.env_detect import ScriptEnvironment
        return ScriptEnvironment(
            language="julia",
            has_manifest=True,
            third_party_imports=["JLD2"],
            driver_extension=".jl",
        )

    def test_drac_cuda_directive_present(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3",
            script_env=self._cuda_env(),
        )
        # Narval `module avail cuda` (2026-05-21): cuda/12.2 (default), 12.6, 12.9, 13.2.
        # 12.2 matches the version pin in LocalPreferences.toml.
        assert "module load cuda/12.2" in prompt
        assert "MUST also emit" in prompt
        # The instruction explains why so the AI doesn't dismiss it.
        assert "LD_LIBRARY_PATH" in prompt

    def test_drac_non_cuda_no_cuda_directive(self, narval_probe, narval_profile):
        """A Julia DRAC job without CUDA shouldn't get the cuda instruction."""
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="cpubase_bycore_b3",
            script_env=self._no_cuda_env(),
        )
        # Neither the old (wrong) name nor the new (correct) name should appear.
        assert "module load cuda/" not in prompt
        assert "cudacore" not in prompt

    def test_grex_cuda_no_drac_cuda_directive(self, grex_probe, grex_profile):
        """Grex compute nodes already have CUDA visible; DRAC-specific cuda module load isn't needed."""
        prompt = _build_system_prompt(
            grex_probe, grex_profile, partition="stamps",
            script_env=self._cuda_env(),
        )
        # The DRAC-specific "MUST also emit module load cuda/..." instruction
        # must NOT appear on Grex. The general rules elsewhere in the prompt
        # may mention `module load` generically, so we check the directive
        # block's distinctive phrasing.
        assert "module load cuda/12.2" not in prompt
        assert "cudacore" not in prompt


class TestDracPythonEnvSetup:
    """On DRAC, ClusterPilot's preflight does `pip install --user` on the
    login node, so the compute-node script must skip pip install entirely
    (no internet there).
    """

    def _python_env(self, manifest_name="requirements.txt", imports=None):
        from clusterpilot.jobs.env_detect import ScriptEnvironment
        return ScriptEnvironment(
            language="python",
            has_manifest=bool(manifest_name),
            third_party_imports=imports or [],
            driver_extension=".py",
            manifest_name=manifest_name,
        )

    def test_drac_python_env_block_says_do_not_pip(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="cpubase_bycore_b3",
            script_env=self._python_env(),
        )
        # The DRAC-python branch must explicitly tell the AI not to emit pip install.
        assert "DO NOT emit" in prompt
        assert "pip install" in prompt
        assert "pre-installed on the login node" in prompt

    def test_drac_python_no_compute_node_pip_install_command(self, narval_probe, narval_profile):
        """The actual `pip install --quiet -r requirements.txt` command shape
        the AI would normally emit on non-DRAC clusters must be absent from
        the DRAC branch — otherwise the AI may copy it into the script.
        """
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="cpubase_bycore_b3",
            script_env=self._python_env(),
        )
        # The directive block should not show `pip install -r requirements.txt`
        # as something to emit; that's the bug we're guarding against.
        assert "pip install --quiet -r requirements.txt" not in prompt
        assert "pip install --quiet -e ." not in prompt

    def test_grex_python_env_unchanged(self, grex_probe, grex_profile):
        """Grex still gets the manifest install instruction (compute nodes have internet)."""
        prompt = _build_system_prompt(
            grex_probe, grex_profile, partition="stamps",
            script_env=self._python_env(),
        )
        # grex_profile is cluster_type='generic' (default fixture) — same path as Grex.
        assert "pip install --quiet -r requirements.txt" in prompt
        assert "DO NOT emit" not in prompt or "pip install" not in prompt.split("DO NOT emit")[0]


class TestModulePurgeOmittedOnStickyEnvironments:
    """Rule 3's `module purge` is a no-op on DRAC (StdEnv/2023 sticky) and on
    Grex (SBEnv sticky) — it only generates the "The following modules were
    not unloaded" warning in every job log. Drop the line on both. Keep it
    on generic clusters as defensive hygiene.
    """

    def _grex_with_real_cluster_type(self):
        """Distinct from the grex_profile fixture which is cluster_type='generic'."""
        return ClusterProfile(
            name="grex",
            host="yak.hpc.umanitoba.ca",
            user="juliaf",
            account="def-stamps",
            scratch="$HOME/clusterpilot_jobs",
            cluster_type="grex",
        )

    def test_drac_omits_module_purge(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(narval_probe, narval_profile, partition="cpubase_bycore_b3")
        # Rule 3's bulleted module-purge bullet must not appear.
        assert "- module purge" not in prompt

    def test_grex_omits_module_purge(self, grex_probe):
        prompt = _build_system_prompt(
            grex_probe, self._grex_with_real_cluster_type(), partition="stamps",
        )
        assert "- module purge" not in prompt

    def test_generic_keeps_module_purge(self, grex_probe, grex_profile):
        """grex_profile defaults to cluster_type='generic' — defensive purge stays."""
        prompt = _build_system_prompt(grex_probe, grex_profile, partition="stamps")
        assert "- module purge" in prompt


class TestNoStdbufRule:
    """#12: the model reaches for `stdbuf -oL` to unbuffer job output. On
    Alliance clusters the libstdbuf.so it preloads breaks CUDA's ptxas
    ("GLIBC_ABI_DT_RELR not found"), and it does nothing for Julia in the first
    place. The prohibition is a generic rule, so it must reach every cluster
    type, not just DRAC.
    """

    def _grex_typed_profile(self):
        return ClusterProfile(
            name="grex",
            host="yak.hpc.umanitoba.ca",
            user="juliaf",
            account="def-stamps",
            scratch="$HOME/clusterpilot_jobs",
            cluster_type="grex",
        )

    def test_drac_prompt_forbids_stdbuf(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3"
        )
        assert "Never wrap the driver in `stdbuf` or set LD_PRELOAD" in prompt
        # The reason wraps across two prompt lines, so match the token itself.
        assert "GLIBC_ABI_DT_RELR" in prompt

    def test_grex_prompt_forbids_stdbuf(self, grex_probe):
        prompt = _build_system_prompt(
            grex_probe, self._grex_typed_profile(), partition="stamps"
        )
        assert "Never wrap the driver in `stdbuf` or set LD_PRELOAD" in prompt

    def test_generic_prompt_forbids_stdbuf(self, grex_probe, grex_profile):
        """grex_profile defaults to cluster_type='generic'."""
        prompt = _build_system_prompt(grex_probe, grex_profile, partition="stamps")
        assert "Never wrap the driver in `stdbuf` or set LD_PRELOAD" in prompt

    def test_python_alternative_is_named(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile, partition="stamps")
        assert "for Python use `python -u`" in prompt


# ── #22: node cores and memory in the partition table ─────────────────────────

class TestPartitionResourcesInTheTable:
    """Issue #22: sinfo now reports %c and %m, so the model can size
    --cpus-per-task and --mem against a real node instead of guessing.
    """

    def _sized_probe(self):
        return ClusterProbe(
            cluster_name="grex", probed_at=time.time(),
            partitions=[
                PartitionInfo(
                    "skylake", "7-00:00:00", "", 10, is_default=True,
                    cpus=52, memory_mb=192 * 1024,
                ),
            ],
            julia_versions=[], accounts=[], account_max_wall={},
        )

    def test_cores_and_memory_are_rendered(self):
        result = _format_partitions(self._sized_probe())
        assert "cpus=52" in result
        assert "mem=192G" in result

    def test_a_probe_without_them_renders_as_before(self, grex_probe):
        result = _format_partitions(grex_probe)
        assert "cpus=" not in result
        assert "mem=" not in result
        assert "skylake        nodes=10   max=7-00:00:00  (CPU only)  [DEFAULT]" in result

    def test_the_sizing_rule_is_in_the_prompt(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile)
        assert (
            "Size --cpus-per-task and --mem from the partition table above; "
            "never request\n   more than a node has." in prompt
        )


# ── #23: the account's probed walltime ceiling ────────────────────────────────

class TestAccountWalltimeCeiling:
    """Issue #23: account_max_wall was probed and never used. An account
    ceiling is enforced independently of the partition's, so it has to reach
    the model.
    """

    def test_present_in_the_drac_routing_hint(self, narval_probe, narval_profile):
        narval_probe.account_max_wall = {"def-stamps": "1-00:00:00"}
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3"
        )
        assert "Account walltime ceiling: 1-00:00:00 (hard limit)" in prompt

    def test_stated_once_only(self, narval_probe, narval_profile):
        narval_probe.account_max_wall = {"def-stamps": "1-00:00:00"}
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3"
        )
        assert prompt.count("Account walltime ceiling") == 1

    def test_present_without_a_picked_partition(self, narval_probe, narval_profile):
        narval_probe.account_max_wall = {"def-stamps": "1-00:00:00"}
        prompt = _build_system_prompt(narval_probe, narval_profile)
        assert "Account walltime ceiling: 1-00:00:00 (hard limit)" in prompt

    def test_present_on_a_generic_cluster(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile, partition="stamps")
        assert "Account walltime ceiling: 7-00:00:00 (hard limit)" in prompt

    def test_absent_when_the_account_is_not_in_the_dict(self, grex_probe, grex_profile):
        grex_probe.account_max_wall = {}
        prompt = _build_system_prompt(grex_probe, grex_profile, partition="stamps")
        assert "Account walltime ceiling" not in prompt

    def test_absent_when_the_ceiling_is_empty(self, narval_probe, narval_profile):
        # sacctmgr is best-effort on DRAC: an unlimited account reports "".
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3"
        )
        assert "Account walltime ceiling" not in prompt


# ── #31: the in-script GPU usage sampler ──────────────────────────────────────

class TestGpuUsageSampler:
    """Issue #31: a GPU job that never reports what it used cannot be sized
    properly next time. The sampler runs on every cluster type.
    """

    def _cuda_env(self):
        from clusterpilot.jobs.env_detect import ScriptEnvironment
        return ScriptEnvironment(
            language="julia",
            has_manifest=True,
            third_party_imports=["CUDA"],
            driver_extension=".jl",
        )

    @pytest.mark.parametrize("cluster_type", ["drac", "grex", "generic"])
    def test_the_sampler_is_in_the_gpu_block(self, grex_probe, cluster_type):
        profile = ClusterProfile(
            name="c", host="h", user="u", account="def-stamps",
            scratch="$HOME/jobs", cluster_type=cluster_type,
        )
        prompt = _build_system_prompt(
            grex_probe, profile, partition="stamps", script_env=self._cuda_env()
        )
        block = gpu_block(prompt)
        assert "nvidia-smi --query-gpu=utilization.gpu,memory.used" in block
        assert "gpu_usage.csv" in block
        assert "kill %1 2>/dev/null || true" in block

    def test_no_sampler_without_a_gpu_job(self, grex_probe, grex_profile):
        prompt = _build_system_prompt(grex_probe, grex_profile, partition="stamps")
        assert "nvidia-smi" not in prompt


# ── #29: Trillium is not a general-purpose DRAC cluster ───────────────────────

@pytest.fixture
def trillium_probe():
    return ClusterProbe(
        cluster_name="trillium",
        probed_at=time.time(),
        partitions=[
            PartitionInfo(
                "compute", "1-00:00:00", "gpu:h100:4", 60, is_default=True,
                cpus=192, memory_mb=768 * 1024,
            ),
        ],
        julia_versions=["julia/1.11.3"],
        accounts=["def-stamps"],
        account_max_wall={"def-stamps": ""},
        scratch_env="/scratch/juliaf",
    )


@pytest.fixture
def trillium_profile():
    return ClusterProfile(
        name="trillium",
        host="trillium-gpu.alliancecan.ca",
        user="juliaf",
        account="def-stamps",
        scratch="$SCRATCH/clusterpilot_jobs",
        cluster_type="trillium",
    )


class TestTrilliumPrompt:
    """Issue #29: Trillium shares DRAC's routed scheduling, $SCRATCH policy,
    sticky module environment and offline compute nodes, and nothing else.
    Whole-node scheduling, a 24 h cap, an ignored --mem and a read-only $HOME
    are its own.
    """

    def _cuda_env(self):
        from clusterpilot.jobs.env_detect import ScriptEnvironment
        return ScriptEnvironment(
            language="julia",
            has_manifest=True,
            third_party_imports=["CUDA"],
            driver_extension=".jl",
        )

    def test_no_hard_partition_directive(self, trillium_probe, trillium_profile):
        prompt = _build_system_prompt(
            trillium_probe, trillium_profile, partition="compute"
        )
        assert "   --partition      " not in prompt
        assert "MUST use exactly `--partition=" not in prompt
        assert "TRILLIUM SCHEDULING" in prompt

    def test_no_module_purge(self, trillium_probe, trillium_profile):
        prompt = _build_system_prompt(trillium_probe, trillium_profile)
        assert "module purge" not in prompt

    def test_gpu_request_is_gpus_per_node(self, trillium_probe, trillium_profile):
        prompt = _build_system_prompt(
            trillium_probe, trillium_profile, partition="compute",
            script_env=self._cuda_env(),
        )
        block = gpu_block(prompt)
        assert "#SBATCH --gpus-per-node=1" in block
        assert "--gres=" not in block

    def test_the_rules_block_forbids_gres_and_mem(self, trillium_probe, trillium_profile):
        prompt = _build_system_prompt(trillium_probe, trillium_profile)
        assert "TRILLIUM RULES" in prompt
        assert "Never emit --gres" in prompt
        assert "NEVER emit --mem" in prompt

    def test_the_twenty_four_hour_cap_is_stated(self, trillium_probe, trillium_profile):
        prompt = _build_system_prompt(trillium_probe, trillium_profile)
        assert "--time must never exceed 24:00:00" in prompt

    def test_home_is_read_only(self, trillium_probe, trillium_profile):
        prompt = _build_system_prompt(trillium_probe, trillium_profile)
        assert "$HOME and $PROJECT are READ-ONLY from compute nodes" in prompt
        assert "must land under $SCRATCH" in prompt

    def test_slurm_tmpdir_is_a_ram_disk_not_an_ssd(self, trillium_probe, trillium_profile):
        prompt = _build_system_prompt(trillium_probe, trillium_profile)
        assert "RAM disk" in prompt
        assert "fast local node SSD" not in prompt

    def test_the_script_must_not_submit_jobs(self, trillium_probe, trillium_profile):
        prompt = _build_system_prompt(trillium_probe, trillium_profile)
        assert "The script must not submit jobs" in prompt

    def test_the_offline_julia_branch_is_shared_with_drac(
        self, trillium_probe, trillium_profile
    ):
        prompt = _build_system_prompt(
            trillium_probe, trillium_profile, script_env=self._cuda_env()
        )
        assert "JULIA_PKG_OFFLINE=true" in prompt
        assert "Do NOT run Pkg.instantiate() or Pkg.add()" in prompt

    def test_the_cuda_module_note_is_shared_with_drac(
        self, trillium_probe, trillium_profile
    ):
        prompt = _build_system_prompt(
            trillium_probe, trillium_profile, partition="compute",
            script_env=self._cuda_env(),
        )
        assert "module load cuda/12.2" in prompt

    def test_a_picked_gpu_size_becomes_a_count_not_a_type(
        self, trillium_probe, trillium_profile
    ):
        prompt = _build_system_prompt(
            trillium_probe, trillium_profile, partition="compute",
            gpu_size="h100", script_env=self._cuda_env(),
        )
        block = gpu_block(prompt)
        assert "--gres=gpu:h100:1" not in block
        assert "emit `--gpus-per-node=1`" in block

    def test_no_trillium_block_on_any_other_cluster_type(
        self, narval_probe, narval_profile, grex_probe, grex_profile
    ):
        for probe, profile in (
            (narval_probe, narval_profile), (grex_probe, grex_profile)
        ):
            prompt = _build_system_prompt(probe, profile)
            assert "TRILLIUM" not in prompt


# ── #41: the hosted proxy streams newline-delimited JSON ──────────────────────

class _FakeStreamResponse:
    """A stand-in for the streaming half of httpx's response."""

    def __init__(self, status_code: int, lines: list[str] | None = None, body: bytes = b""):
        self.status_code = status_code
        self._lines = lines or []
        self._body = body

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return self._body


class _FakePostResponse:
    def __init__(self, status_code: int, payload: dict, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Records the URLs asked for and answers with prepared responses."""

    def __init__(self, stream_response, post_response=None):
        self.stream_response = stream_response
        self.post_response = post_response
        self.urls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, **kwargs):
        self.urls.append(url)
        client = self

        class _Ctx:
            async def __aenter__(self):
                return client.stream_response

            async def __aexit__(self, *exc):
                return False

        return _Ctx()

    async def post(self, url, **kwargs):
        self.urls.append(url)
        return self.post_response


async def _collect(agen) -> list[str]:
    return [token async for token in agen]


def _install(monkeypatch, client) -> None:
    from clusterpilot.jobs import ai_gen
    monkeypatch.setattr(ai_gen.httpx, "AsyncClient", lambda **kw: client)


class TestProxyStreaming:
    """Issue #41: the hosted tier stopped streaming when generation moved to a
    single POST. The client now reads newline-delimited JSON as it arrives and
    falls back to that POST only when the endpoint is not deployed yet.
    """

    def _stream(self, usage=None):
        from clusterpilot.jobs.ai_gen import _stream_proxy
        return _stream_proxy(
            "system", "description", "claude-sonnet-4-6", "cp-token",
            "https://api.clusterpilot.sh/proxy", usage,
        )

    @pytest.mark.asyncio
    async def test_deltas_arrive_in_order(self, monkeypatch):
        client = _FakeClient(_FakeStreamResponse(200, [
            '{"text": "#!/bin/bash\\n"}',
            '{"text": "#SBATCH --time=01:00:00\\n"}',
            '',
            '{"done": true, "input_tokens": 1200, "output_tokens": 340, "stop_reason": "end_turn"}',
        ]))
        _install(monkeypatch, client)
        usage = ApiUsage()
        tokens = await _collect(self._stream(usage))
        assert tokens == ["#!/bin/bash\n", "#SBATCH --time=01:00:00\n"]
        assert client.urls == ["https://api.clusterpilot.sh/proxy/generate-stream"]
        assert usage.model == "claude-sonnet-4-6"
        assert (usage.input_tokens, usage.output_tokens) == (1200, 340)
        assert usage.stop_reason == "end_turn"
        assert usage.truncated is False

    @pytest.mark.asyncio
    async def test_a_truncated_generation_is_still_visible(self, monkeypatch):
        client = _FakeClient(_FakeStreamResponse(200, [
            '{"text": "#!/bin/bash"}',
            '{"done": true, "stop_reason": "max_tokens"}',
        ]))
        _install(monkeypatch, client)
        usage = ApiUsage()
        await _collect(self._stream(usage))
        assert usage.truncated is True

    @pytest.mark.asyncio
    async def test_an_error_line_raises(self, monkeypatch):
        client = _FakeClient(_FakeStreamResponse(200, [
            '{"text": "#!/bin/bash"}',
            '{"error": "subscription inactive"}',
        ]))
        _install(monkeypatch, client)
        with pytest.raises(RuntimeError, match="subscription inactive"):
            await _collect(self._stream())

    @pytest.mark.asyncio
    async def test_a_404_falls_back_to_the_single_post(self, monkeypatch):
        client = _FakeClient(
            _FakeStreamResponse(404, body=b"Not Found"),
            _FakePostResponse(200, {
                "text": "#!/bin/bash\necho hi\n",
                "input_tokens": 10,
                "output_tokens": 5,
                "stop_reason": "end_turn",
            }),
        )
        _install(monkeypatch, client)
        usage = ApiUsage()
        tokens = await _collect(self._stream(usage))
        assert "".join(tokens) == "#!/bin/bash\necho hi\n"
        assert client.urls == [
            "https://api.clusterpilot.sh/proxy/generate-stream",
            "https://api.clusterpilot.sh/proxy/generate",
        ]
        assert (usage.input_tokens, usage.output_tokens) == (10, 5)

    @pytest.mark.asyncio
    async def test_a_405_falls_back_too(self, monkeypatch):
        client = _FakeClient(
            _FakeStreamResponse(405, body=b"Method Not Allowed"),
            _FakePostResponse(200, {"text": "ok"}),
        )
        _install(monkeypatch, client)
        assert "".join(await _collect(self._stream())) == "ok"

    @pytest.mark.asyncio
    async def test_any_other_status_raises_without_falling_back(self, monkeypatch):
        client = _FakeClient(_FakeStreamResponse(402, body=b"payment required"))
        _install(monkeypatch, client)
        with pytest.raises(RuntimeError, match="HTTP 402"):
            await _collect(self._stream())
        assert client.urls == ["https://api.clusterpilot.sh/proxy/generate-stream"]

    @pytest.mark.asyncio
    async def test_the_fallback_still_reports_a_bad_status(self, monkeypatch):
        client = _FakeClient(
            _FakeStreamResponse(404, body=b"Not Found"),
            _FakePostResponse(500, {}, text="upstream exploded"),
        )
        _install(monkeypatch, client)
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await _collect(self._stream())


class TestPricing:
    """Sonnet 5 and Opus 5 are priced; the 4.6 rows stay for existing configs."""

    def test_sonnet_5_is_priced(self):
        usage = ApiUsage(model="claude-sonnet-5",
                         input_tokens=1_000_000, output_tokens=1_000_000)
        assert usage.cost_usd == pytest.approx(12.00)

    def test_opus_5_is_priced(self):
        usage = ApiUsage(model="claude-opus-5",
                         input_tokens=1_000_000, output_tokens=1_000_000)
        assert usage.cost_usd == pytest.approx(30.00)

    def test_the_4_6_rows_are_kept(self):
        assert price_for("claude-sonnet-4-6") == (3.00, 15.00)
        assert price_for("claude-opus-4-6") == (5.00, 25.00)

    def test_haiku_4_5_is_priced_at_the_published_rate(self):
        """This row read (0.80, 4.00) until #67 and was 20% low."""
        assert price_for("claude-haiku-4-5") == (1.00, 5.00)

    def test_an_unknown_model_is_unknown_rather_than_free(self):
        """Changed by #67. It used to answer 0.0, which reads as "this cost
        nothing" and is only true for a local model. A model released since
        this table was last checked costs something nobody here knows, and the
        display has to be able to tell the two apart from a real zero."""
        usage = ApiUsage(model="llama3.2", input_tokens=1000, output_tokens=1000)
        assert usage.cost_usd is None
        assert price_for("llama3.2") is None
        assert estimate_cost("llama3.2", 1000, 1000) is None


class TestAllowanceFieldsFromTheProxy:
    """The proxy reports which model it actually used and what is left of the
    month's allowance. The fields are additions, so an API that predates them
    must leave every default in place rather than read as a spent allowance.
    """

    def _stream(self, usage):
        from clusterpilot.jobs.ai_gen import _stream_proxy
        return _stream_proxy(
            "system", "description", "claude-opus-5", "cp-token",
            "https://api.clusterpilot.sh/proxy", usage,
        )

    @pytest.mark.asyncio
    async def test_the_done_line_carries_the_substitution(self, monkeypatch):
        client = _FakeClient(_FakeStreamResponse(200, [
            '{"text": "#!/bin/bash\\n"}',
            '{"done": true, "input_tokens": 10, "output_tokens": 5,'
            ' "stop_reason": "end_turn", "model_used": "claude-sonnet-5",'
            ' "fallback": true, "remaining_opus": 0, "remaining_total": 109}',
        ]))
        _install(monkeypatch, client)
        usage = ApiUsage()
        await _collect(self._stream(usage))
        assert usage.model == "claude-sonnet-5"
        assert usage.fallback is True
        assert usage.remaining_opus == 0
        assert usage.remaining_total == 109

    @pytest.mark.asyncio
    async def test_the_done_line_without_the_fields_is_unchanged(self, monkeypatch):
        client = _FakeClient(_FakeStreamResponse(200, [
            '{"text": "#!/bin/bash\\n"}',
            '{"done": true, "input_tokens": 10, "output_tokens": 5,'
            ' "stop_reason": "end_turn"}',
        ]))
        _install(monkeypatch, client)
        usage = ApiUsage()
        await _collect(self._stream(usage))
        assert usage.model == "claude-opus-5"   # the model asked for
        assert usage.fallback is False
        assert usage.remaining_opus is None
        assert usage.remaining_total is None

    @pytest.mark.asyncio
    async def test_the_json_response_carries_the_substitution(self, monkeypatch):
        client = _FakeClient(
            _FakeStreamResponse(404, body=b"Not Found"),
            _FakePostResponse(200, {
                "text": "#!/bin/bash\n",
                "input_tokens": 10,
                "output_tokens": 5,
                "stop_reason": "end_turn",
                "model_used": "claude-sonnet-5",
                "fallback": True,
                "remaining_opus": 0,
                "remaining_total": 42,
            }),
        )
        _install(monkeypatch, client)
        usage = ApiUsage()
        await _collect(self._stream(usage))
        assert usage.model == "claude-sonnet-5"
        assert usage.fallback is True
        assert (usage.remaining_opus, usage.remaining_total) == (0, 42)

    @pytest.mark.asyncio
    async def test_the_json_response_without_the_fields_is_unchanged(self, monkeypatch):
        client = _FakeClient(
            _FakeStreamResponse(404, body=b"Not Found"),
            _FakePostResponse(200, {
                "text": "#!/bin/bash\n",
                "input_tokens": 10,
                "output_tokens": 5,
                "stop_reason": "end_turn",
            }),
        )
        _install(monkeypatch, client)
        usage = ApiUsage()
        await _collect(self._stream(usage))
        assert usage.model == "claude-opus-5"
        assert usage.fallback is False
        assert usage.remaining_opus is None
        assert usage.remaining_total is None
