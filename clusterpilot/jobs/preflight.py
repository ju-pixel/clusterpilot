"""Pre-flight dependency installation on cluster login nodes.

DRAC compute nodes (Narval, Cedar, Beluga, Graham) have no outbound internet
by Alliance Canada policy. Login nodes do. This module warms the user's
package depot on the login node BEFORE sbatch, so the compute-node script
can run offline against the depot via the NFS-shared ``$HOME``.

Public entry point: :func:`warm_depot`. Dispatches on ``env.language``.
Phase A implements Julia; Phase B will add Python.
"""
from __future__ import annotations

import re
import shlex

from clusterpilot.jobs.env_detect import ScriptEnvironment
from clusterpilot.ssh.connection import SSHError, run_remote


# Cold instantiate of a CUDA-heavy Manifest (CUDA_Compiler_jll, CUDA_Runtime_jll
# etc.) on a DRAC login node can take 15-25 minutes the very first time because
# Julia downloads several hundred MB of binary artifacts. After the first warm,
# subsequent instantiate calls against the same depot are sub-minute. 30 min is
# the headroom we give first-run cold warms.
_DEFAULT_TIMEOUT = 1800.0


class PreflightError(Exception):
    """Raised when login-node dependency installation fails.

    The captured remote stderr (if any) is on :attr:`stderr` so the caller
    can persist it to disk for the user to read later.
    """

    def __init__(self, message: str, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


# ── Public API ────────────────────────────────────────────────────────────────


async def warm_depot(
    host: str,
    user: str,
    remote_dir: str,
    env: ScriptEnvironment,
    *,
    script: str = "",
    cluster_type: str = "",
    timeout: float = _DEFAULT_TIMEOUT,
) -> bool:
    """Warm the user's package depot for *env* on the login node.

    Args:
        host:         SSH hostname of the cluster login node.
        user:         Remote username.
        remote_dir:   Absolute path of the rsynced project on the cluster.
        env:          Static analysis of the driver script.
        script:       The generated SLURM script, used to recover the exact
                      ``module load`` line (so the login-node Julia matches the
                      compute-node Julia).
        cluster_type: ``"drac"``, ``"grex"``, or ``"generic"``. Triggers
                      DRAC-specific quirk handling (writing
                      ``LocalPreferences.toml`` for CUDA.jl).
        timeout:      Maximum seconds to wait for the install command.

    Returns:
        True if a pre-flight step actually ran; False if there was nothing
        to do (shell script, empty manifest, no detected imports, unsupported
        language).

    Raises:
        PreflightError: if the install command exited non-zero or timed out.
    """
    if env.language == "julia":
        return await _warm_julia(host, user, remote_dir, env, script, cluster_type, timeout)
    if env.language == "python":
        return await _warm_python(host, user, remote_dir, env, script, cluster_type, timeout)
    return False


# ── Julia ────────────────────────────────────────────────────────────────────


async def _warm_julia(
    host: str,
    user: str,
    remote_dir: str,
    env: ScriptEnvironment,
    script: str,
    cluster_type: str,
    timeout: float,
) -> bool:
    if not env.has_manifest and not env.third_party_imports:
        return False

    julia_module = _extract_julia_module(script) or "julia"

    # DRAC quirk: a login-node `Pkg.instantiate()` precompiles CUDA_Runtime_jll
    # without a GPU visible. Compute-node Julia then refuses to use it ("CUDA.jl's
    # JLLs were precompiled without an NVIDIA driver present"). Setting
    # `local_toolkit = true` in LocalPreferences.toml tells CUDA.jl to defer to
    # the system CUDA on LD_LIBRARY_PATH at runtime — the cudacore module loaded
    # on the compute node provides libcuda.so. The `[ -f ... ]` guard lets a
    # user-authored LocalPreferences.toml from their project tree win.
    if (
        cluster_type == "drac"
        and "CUDA" in env.third_party_imports
    ):
        await _ensure_drac_cuda_preferences(host, user, remote_dir)

    if env.has_manifest:
        julia_expr = "using Pkg; Pkg.instantiate()"
    else:
        pkgs = ", ".join(f'"{p}"' for p in env.third_party_imports)
        julia_expr = f"using Pkg; Pkg.add([{pkgs}]); Pkg.instantiate()"

    cmd = (
        f"module load {julia_module} && "
        f"cd {shlex.quote(remote_dir)} && "
        f"julia --project=. -e {shlex.quote(julia_expr)}"
    )
    await _run_or_raise(host, user, cmd, timeout)
    return True


_DRAC_CUDA_PREFERENCES = (
    '[CUDA_Runtime_jll]\n'
    'version = "12.2"\n'
    'local_toolkit = true\n'
)


# ── Python ───────────────────────────────────────────────────────────────────

# Common Python import → PyPI distribution name mappings. Mirrors the list
# in ``jobs/ai_gen.py`` so the pre-flight installs the right wheels when the
# user has no manifest and we have to fall back to inferred imports.
_PYTHON_IMPORT_TO_PYPI: dict[str, str] = {
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "skimage": "scikit-image",
    "yaml": "PyYAML",
}


async def _warm_python(
    host: str,
    user: str,
    remote_dir: str,
    env: ScriptEnvironment,
    script: str,
    cluster_type: str,
    timeout: float,
) -> bool:
    """Pre-install Python dependencies on the login node.

    Only relevant on DRAC: Alliance Canada compute nodes have no outbound
    internet, but the login node does and ``$HOME/.local`` is NFS-shared
    between the two. On Grex and generic clusters the compute node can
    reach PyPI directly, so the AI's in-script pip install is sufficient
    and this function is a no-op.
    """
    if cluster_type != "drac":
        return False
    if not env.has_manifest and not env.third_party_imports:
        return False

    python_module = _extract_python_module(script) or "python"

    if env.has_manifest:
        if env.manifest_name == "requirements.txt":
            pip_install = "pip install --user --quiet -r requirements.txt"
        elif env.manifest_name == "pyproject.toml":
            # Editable install also makes the project's own package importable
            # under its declared name. Non-editable would re-copy on every
            # submission since the source dir is timestamped.
            pip_install = "pip install --user --quiet -e ."
        else:
            # Unknown manifest type (e.g. Project.toml is Julia, not Python).
            return False
    else:
        pkgs = " ".join(
            shlex.quote(_PYTHON_IMPORT_TO_PYPI.get(p, p))
            for p in env.third_party_imports
        )
        pip_install = f"pip install --user --quiet {pkgs}"

    # Always upgrade pip first — DRAC's bundled pip is often old enough that
    # modern wheels (numpy 2.x, torch 2.x) fail to install with cryptic errors.
    cmd = (
        f"module load {python_module} && "
        f"cd {shlex.quote(remote_dir)} && "
        f"pip install --user --quiet --upgrade pip && "
        f"{pip_install}"
    )
    await _run_or_raise(host, user, cmd, timeout)
    return True


def _extract_python_module(script: str) -> str | None:
    """Return the first ``python/X.Y.Z`` module-load token from *script*.

    Falls back to None if the script has no ``module load python/...`` line,
    in which case the caller defaults to the bare ``python`` module name.
    """
    match = re.search(r"^\s*module\s+load\s+(python/[\d.]+)", script, re.MULTILINE)
    return match.group(1) if match else None


# ── Internals ────────────────────────────────────────────────────────────────


async def _ensure_drac_cuda_preferences(host: str, user: str, remote_dir: str) -> None:
    """Write LocalPreferences.toml into *remote_dir* unless one already exists.

    Uses a quoted heredoc so the prefs content is sent verbatim — no shell
    expansion. The leading `[ -f ... ]` guard means a user-shipped
    LocalPreferences.toml (e.g. pinned to a different CUDA version) is never
    clobbered.
    """
    cmd = (
        f"cd {shlex.quote(remote_dir)} && "
        f"if [ ! -f LocalPreferences.toml ]; then "
        f"cat > LocalPreferences.toml <<'CPEOF'\n"
        f"{_DRAC_CUDA_PREFERENCES}"
        f"CPEOF\n"
        f"fi"
    )
    await _run_or_raise(host, user, cmd, timeout=30.0)


def _extract_julia_module(script: str) -> str | None:
    """Return the first ``julia/X.Y.Z`` module-load token from *script*.

    Falls back to None if the script has no ``module load julia/...`` line,
    in which case the caller defaults to the bare ``julia`` module name.
    """
    match = re.search(r"^\s*module\s+load\s+(julia/[\d.]+)", script, re.MULTILINE)
    return match.group(1) if match else None


# ── Internals ────────────────────────────────────────────────────────────────


async def _run_or_raise(host: str, user: str, cmd: str, timeout: float) -> str:
    try:
        return await run_remote(host, user, cmd, timeout=timeout)
    except SSHError as exc:
        msg = str(exc)
        if "timed out" in msg.lower():
            hint = (
                f"\n\nTimed out after {timeout:.0f}s. The very first cold instantiate of a "
                "CUDA-heavy Manifest can take 15-25 minutes on a DRAC login node. "
                "Options:\n"
                "  (a) re-run submission; depot may already be partially warm and "
                "subsequent attempts get further\n"
                "  (b) pre-warm manually in a separate terminal: "
                "ssh <user>@<host> 'cd <remote_dir> && module load <julia-module> && "
                "julia --project=. -e \"using Pkg; Pkg.instantiate()\"' "
                "and then resubmit\n"
                "  (c) increase the timeout via the warm_depot timeout= kwarg"
            )
            raise PreflightError(msg + hint, stderr=msg + hint) from exc
        raise PreflightError(
            f"Login-node dependency install failed: {exc}",
            stderr=msg,
        ) from exc
