"""Tests for jobs/preflight.py — login-node dependency warming.

The actual SSH call is mocked; what we verify is that the right shell command
is built for each language/manifest combination and that PreflightError
carries useful context on failure.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from clusterpilot.jobs.env_detect import ScriptEnvironment
from clusterpilot.jobs.preflight import (
    PreflightError,
    _extract_julia_module,
    _extract_python_module,
    warm_depot,
)
from clusterpilot.ssh.connection import SSHError


# ── _extract_julia_module ─────────────────────────────────────────────────────

class TestExtractJuliaModule:
    def test_standard_module_load_line(self):
        script = "#!/bin/bash\nmodule purge\nmodule load julia/1.11.3\n"
        assert _extract_julia_module(script) == "julia/1.11.3"

    def test_indented_module_load(self):
        script = "    module load julia/1.10.3\n"
        assert _extract_julia_module(script) == "julia/1.10.3"

    def test_no_julia_load_returns_none(self):
        script = "#!/bin/bash\nmodule load python/3.11\n"
        assert _extract_julia_module(script) is None

    def test_empty_script(self):
        assert _extract_julia_module("") is None

    def test_picks_first_julia_load(self):
        script = "module load julia/1.10.3\nmodule load julia/1.11.3\n"
        assert _extract_julia_module(script) == "julia/1.10.3"


# ── warm_depot — Julia path ───────────────────────────────────────────────────

class TestWarmDepotJulia:
    """Mirrors the Narval 2026-05-21 failure: a Julia job with Project.toml
    needs Pkg.instantiate() run on the login node before sbatch.
    """

    @pytest.mark.asyncio
    async def test_julia_with_manifest_runs_instantiate(self):
        env = ScriptEnvironment(
            language="julia",
            has_manifest=True,
            third_party_imports=[],
            driver_extension=".jl",
        )
        script = "#!/bin/bash\nmodule load julia/1.11.3\n"
        captured: dict = {}

        async def fake_run_remote(host, user, cmd, **kw):
            captured["cmd"] = cmd
            captured["timeout"] = kw.get("timeout")
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            ran = await warm_depot(
                "narval.alliancecan.ca", "juliaf", "/scratch/juliaf/myjob",
                env, script=script,
            )
        assert ran is True
        # Loads the exact Julia version, cd's into the rsynced job dir, runs instantiate.
        assert "module load julia/1.11.3" in captured["cmd"]
        assert "cd /scratch/juliaf/myjob" in captured["cmd"]
        assert "using Pkg; Pkg.instantiate()" in captured["cmd"]
        # Long timeout so cold instantiate has room to finish.
        assert captured["timeout"] >= 300

    @pytest.mark.asyncio
    async def test_julia_no_manifest_with_imports_runs_pkg_add(self):
        env = ScriptEnvironment(
            language="julia",
            has_manifest=False,
            third_party_imports=["CUDA", "Flux"],
            driver_extension=".jl",
        )
        script = "module load julia/1.11.3\n"
        captured: dict = {}

        async def fake_run_remote(host, user, cmd, **kw):
            captured["cmd"] = cmd
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            ran = await warm_depot(
                "narval.alliancecan.ca", "juliaf", "/scratch/juliaf/job", env,
                script=script,
            )
        assert ran is True
        assert 'Pkg.add(["CUDA", "Flux"])' in captured["cmd"]
        assert "Pkg.instantiate()" in captured["cmd"]

    @pytest.mark.asyncio
    async def test_julia_empty_env_no_op(self):
        """A Julia script with no manifest and no detected imports is a no-op."""
        env = ScriptEnvironment(
            language="julia",
            has_manifest=False,
            third_party_imports=[],
            driver_extension=".jl",
        )
        called = {"n": 0}

        async def fake_run_remote(host, user, cmd, **kw):
            called["n"] += 1
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            ran = await warm_depot(
                "narval.alliancecan.ca", "juliaf", "/scratch/juliaf/job", env,
            )
        assert ran is False
        assert called["n"] == 0

    @pytest.mark.asyncio
    async def test_falls_back_to_bare_julia_module_when_load_line_missing(self):
        env = ScriptEnvironment(
            language="julia",
            has_manifest=True,
            third_party_imports=[],
            driver_extension=".jl",
        )
        captured: dict = {}

        async def fake_run_remote(host, user, cmd, **kw):
            captured["cmd"] = cmd
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            await warm_depot(
                "narval.alliancecan.ca", "juliaf", "/scratch/juliaf/job", env,
                script="",
            )
        assert "module load julia" in captured["cmd"]

    @pytest.mark.asyncio
    async def test_ssh_failure_raises_preflight_error_with_stderr(self):
        env = ScriptEnvironment(
            language="julia",
            has_manifest=True,
            third_party_imports=[],
            driver_extension=".jl",
        )
        ssh_message = (
            "Remote command failed (exit 1): ...\n"
            "ERROR: expected package CUDA_Compiler_jll to be registered"
        )

        async def fake_run_remote(host, user, cmd, **kw):
            raise SSHError(ssh_message)

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            with pytest.raises(PreflightError) as exc_info:
                await warm_depot(
                    "narval.alliancecan.ca", "juliaf", "/scratch/juliaf/job", env,
                    script="module load julia/1.11.3",
                )
        # The captured stderr is on the exception so submit.py can write it
        # to preflight.log.
        assert "CUDA_Compiler_jll" in exc_info.value.stderr

    @pytest.mark.asyncio
    async def test_non_julia_language_is_noop_for_now(self):
        """Phase A: only Julia. Python returns False so the caller proceeds to sbatch."""
        env = ScriptEnvironment(
            language="python",
            has_manifest=True,
            third_party_imports=[],
            driver_extension=".py",
        )
        called = {"n": 0}

        async def fake_run_remote(host, user, cmd, **kw):
            called["n"] += 1
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            ran = await warm_depot(
                "narval.alliancecan.ca", "juliaf", "/scratch/juliaf/job", env,
            )
        assert ran is False
        assert called["n"] == 0


class TestWarmDepotDracCuda:
    """DRAC compute nodes cannot reach pkg.julialang.org AND login-node
    `Pkg.instantiate()` precompiles CUDA_Runtime_jll without a GPU visible.
    Setting `local_toolkit = true` in LocalPreferences.toml before instantiate
    routes CUDA.jl through the system CUDA toolkit (loaded via cudacore module
    on the compute node) and dodges both problems.

    Narval 2026-05-21 job 61345456: failed with "CUDA driver not functional"
    until LocalPreferences.toml + module load cudacore/12.2.2 were added.
    """

    JULIA_ENV_WITH_CUDA = ScriptEnvironment(
        language="julia",
        has_manifest=True,
        third_party_imports=["CUDA", "JLD2"],
        driver_extension=".jl",
    )

    @pytest.mark.asyncio
    async def test_drac_cuda_writes_local_preferences_first(self):
        commands: list[str] = []

        async def fake_run_remote(host, user, cmd, **kw):
            commands.append(cmd)
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            ran = await warm_depot(
                "narval.alliancecan.ca", "juliaf", "/scratch/juliaf/myjob",
                self.JULIA_ENV_WITH_CUDA,
                script="module load julia/1.11.3",
                cluster_type="drac",
            )
        assert ran is True
        assert len(commands) == 2
        # First command writes LocalPreferences.toml.
        prefs_cmd = commands[0]
        assert "LocalPreferences.toml" in prefs_cmd
        assert "local_toolkit = true" in prefs_cmd
        assert "CUDA_Runtime_jll" in prefs_cmd
        # Guard so a user-shipped LocalPreferences.toml is never clobbered.
        assert "if [ ! -f LocalPreferences.toml ]" in prefs_cmd
        # Second command is the instantiate.
        assert "Pkg.instantiate()" in commands[1]

    @pytest.mark.asyncio
    async def test_grex_cuda_does_not_write_local_preferences(self):
        """Grex compute nodes have internet + native CUDA — no preferences hack needed."""
        commands: list[str] = []

        async def fake_run_remote(host, user, cmd, **kw):
            commands.append(cmd)
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            await warm_depot(
                "yak.hpc.umanitoba.ca", "juliaf", "/home/juliaf/clusterpilot_jobs/myjob",
                self.JULIA_ENV_WITH_CUDA,
                script="module load julia/1.11.3",
                cluster_type="grex",
            )
        # Only one command (instantiate); no LocalPreferences write on Grex.
        assert len(commands) == 1
        assert "LocalPreferences.toml" not in commands[0]

    @pytest.mark.asyncio
    async def test_drac_julia_without_cuda_does_not_write_local_preferences(self):
        """A Julia job that doesn't import CUDA shouldn't get the preferences file."""
        env = ScriptEnvironment(
            language="julia",
            has_manifest=True,
            third_party_imports=["JLD2", "Statistics"],
            driver_extension=".jl",
        )
        commands: list[str] = []

        async def fake_run_remote(host, user, cmd, **kw):
            commands.append(cmd)
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            await warm_depot(
                "narval.alliancecan.ca", "juliaf", "/scratch/juliaf/job", env,
                script="module load julia/1.11.3",
                cluster_type="drac",
            )
        assert len(commands) == 1
        assert "LocalPreferences.toml" not in commands[0]

    @pytest.mark.asyncio
    async def test_local_preferences_guard_is_quoted_heredoc(self):
        """The heredoc marker is single-quoted so $ in the prefs content does not expand."""
        commands: list[str] = []

        async def fake_run_remote(host, user, cmd, **kw):
            commands.append(cmd)
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            await warm_depot(
                "narval.alliancecan.ca", "juliaf", "/scratch/juliaf/job",
                self.JULIA_ENV_WITH_CUDA,
                script="module load julia/1.11.3",
                cluster_type="drac",
            )
        # Quoted heredoc marker prevents $-expansion of any future content.
        assert "<<'CPEOF'" in commands[0]


# ── _extract_python_module ────────────────────────────────────────────────────

class TestExtractPythonModule:
    def test_standard_module_load_line(self):
        script = "#!/bin/bash\nmodule purge\nmodule load python/3.11.5\n"
        assert _extract_python_module(script) == "python/3.11.5"

    def test_no_python_load_returns_none(self):
        script = "#!/bin/bash\nmodule load julia/1.11.3\n"
        assert _extract_python_module(script) is None

    def test_empty_script(self):
        assert _extract_python_module("") is None


# ── warm_depot — Python path (DRAC only) ──────────────────────────────────────

class TestWarmDepotPython:
    """Python pre-flight is DRAC-only: Alliance Canada compute nodes have no
    outbound internet but the login node does, and `$HOME/.local/lib/.../
    site-packages/` is NFS-shared so a login-node `pip install --user`
    populates the compute node automatically.
    """

    @pytest.mark.asyncio
    async def test_python_requirements_txt_runs_pip_dash_r(self):
        env = ScriptEnvironment(
            language="python",
            has_manifest=True,
            third_party_imports=[],
            driver_extension=".py",
            manifest_name="requirements.txt",
        )
        captured: dict = {}

        async def fake_run_remote(host, user, cmd, **kw):
            captured["cmd"] = cmd
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            ran = await warm_depot(
                "narval.alliancecan.ca", "juliaf", "/scratch/juliaf/myjob",
                env, script="module load python/3.11.5",
                cluster_type="drac",
            )
        assert ran is True
        assert "module load python/3.11.5" in captured["cmd"]
        assert "cd /scratch/juliaf/myjob" in captured["cmd"]
        assert "pip install --user --quiet -r requirements.txt" in captured["cmd"]
        # Pip is upgraded first so old pip doesn't choke on modern wheels.
        assert "pip install --user --quiet --upgrade pip" in captured["cmd"]

    @pytest.mark.asyncio
    async def test_python_pyproject_runs_editable_install(self):
        env = ScriptEnvironment(
            language="python",
            has_manifest=True,
            third_party_imports=[],
            driver_extension=".py",
            manifest_name="pyproject.toml",
        )
        captured: dict = {}

        async def fake_run_remote(host, user, cmd, **kw):
            captured["cmd"] = cmd
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            ran = await warm_depot(
                "narval.alliancecan.ca", "juliaf", "/scratch/juliaf/myjob",
                env, script="module load python/3.11.5",
                cluster_type="drac",
            )
        assert ran is True
        # Editable install so the project's own package is importable AND
        # so it doesn't re-copy on every timestamped submission.
        assert "pip install --user --quiet -e ." in captured["cmd"]

    @pytest.mark.asyncio
    async def test_python_no_manifest_uses_inferred_imports_with_name_map(self):
        """Without a manifest, fall back to inferred imports.  Common
        import → PyPI name mappings (sklearn → scikit-learn, cv2 → opencv-python)
        must be applied so the install doesn't 404 on the wrong package name.
        """
        env = ScriptEnvironment(
            language="python",
            has_manifest=False,
            third_party_imports=["numpy", "sklearn", "cv2"],
            driver_extension=".py",
        )
        captured: dict = {}

        async def fake_run_remote(host, user, cmd, **kw):
            captured["cmd"] = cmd
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            ran = await warm_depot(
                "narval.alliancecan.ca", "juliaf", "/scratch/juliaf/myjob",
                env, script="module load python/3.11.5",
                cluster_type="drac",
            )
        assert ran is True
        # Mapped names appear; raw import names do NOT (where mapping exists).
        assert "scikit-learn" in captured["cmd"]
        assert "opencv-python" in captured["cmd"]
        assert "numpy" in captured["cmd"]
        # Bare "sklearn" or "cv2" must not be passed to pip as a distribution name.
        assert " sklearn " not in captured["cmd"] and not captured["cmd"].endswith(" sklearn")
        assert " cv2 " not in captured["cmd"] and not captured["cmd"].endswith(" cv2")

    @pytest.mark.asyncio
    async def test_python_on_grex_is_noop(self):
        """Grex compute nodes have internet — the AI's in-script pip install works.
        Pre-flight must not pre-install (would be redundant and might pollute
        ~/.local with packages the user didn't ask to install globally).
        """
        env = ScriptEnvironment(
            language="python",
            has_manifest=True,
            third_party_imports=[],
            driver_extension=".py",
            manifest_name="requirements.txt",
        )
        called = {"n": 0}

        async def fake_run_remote(host, user, cmd, **kw):
            called["n"] += 1
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            ran = await warm_depot(
                "yak.hpc.umanitoba.ca", "juliaf", "/home/juliaf/myjob",
                env, script="module load python/3.11.5",
                cluster_type="grex",
            )
        assert ran is False
        assert called["n"] == 0

    @pytest.mark.asyncio
    async def test_python_generic_cluster_is_noop(self):
        env = ScriptEnvironment(
            language="python",
            has_manifest=True,
            third_party_imports=[],
            driver_extension=".py",
            manifest_name="requirements.txt",
        )
        called = {"n": 0}

        async def fake_run_remote(host, user, cmd, **kw):
            called["n"] += 1
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            ran = await warm_depot(
                "some.cluster.edu", "user", "/scratch/user/job",
                env, script="module load python/3.11.5",
                cluster_type="generic",
            )
        assert ran is False
        assert called["n"] == 0

    @pytest.mark.asyncio
    async def test_python_empty_env_no_op(self):
        """No manifest and no detected imports → nothing to install."""
        env = ScriptEnvironment(
            language="python",
            has_manifest=False,
            third_party_imports=[],
            driver_extension=".py",
        )
        called = {"n": 0}

        async def fake_run_remote(host, user, cmd, **kw):
            called["n"] += 1
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            ran = await warm_depot(
                "narval.alliancecan.ca", "juliaf", "/scratch/juliaf/job", env,
                cluster_type="drac",
            )
        assert ran is False
        assert called["n"] == 0

    @pytest.mark.asyncio
    async def test_python_unknown_manifest_name_no_op(self):
        """A Julia Project.toml masquerading as a python manifest (or any
        unrecognised filename) should not trigger pip install.
        """
        env = ScriptEnvironment(
            language="python",
            has_manifest=True,
            third_party_imports=[],
            driver_extension=".py",
            manifest_name="Project.toml",   # Wrong type for python
        )
        called = {"n": 0}

        async def fake_run_remote(host, user, cmd, **kw):
            called["n"] += 1
            return ""

        with patch("clusterpilot.jobs.preflight.run_remote", new=fake_run_remote):
            ran = await warm_depot(
                "narval.alliancecan.ca", "juliaf", "/scratch/juliaf/job", env,
                script="module load python/3.11.5",
                cluster_type="drac",
            )
        assert ran is False
        assert called["n"] == 0
