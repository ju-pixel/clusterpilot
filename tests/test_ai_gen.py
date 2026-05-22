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

    def test_picked_partition_becomes_gres_hint(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3"
        )
        # The GRES of gpubase_bynode_b3 (gpu:a100:4) must be surfaced as the
        # hint so the AI matches it in the --gres directive.
        assert "gpu:a100:4" in prompt
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
        # The instantiate call must still be there — idempotent against warm depot,
        # and keeps the script portable to non-DRAC clusters.
        assert "Pkg.instantiate()" in prompt

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
        assert 'Pkg.add(["CUDA", "Flux"])' in prompt


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

    def test_drac_uses_picked_partition_gres_as_default(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3",
            script_env=self._env(["CUDA"]),
        )
        # Picked partition's gres ("gpu:a100:4") seeds the default.
        assert "gpu:a100:4" in prompt

    def test_drac_no_picked_partition_falls_back_to_a100(self, narval_probe, narval_profile):
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="",
            script_env=self._env(["CUDA"]),
        )
        assert "gpu:a100:1" in prompt

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

    def test_drac_still_uses_partition_gres(self, narval_probe, narval_profile):
        """DRAC's behaviour is unchanged: the picked partition's GRES (typed) is the default."""
        prompt = _build_system_prompt(
            narval_probe, narval_profile, partition="gpubase_bynode_b3",
            script_env=self._cuda_env(),
        )
        assert "gpu:a100:4" in prompt
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
