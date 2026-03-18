"""AI-powered SLURM script generation.

Takes the user's plain-language job description and the cluster probe data,
builds a rich system prompt, then streams a complete sbatch script from the
configured model.

Usage
-----
    usage = ApiUsage()
    async for token in generate_script(description, probe, profile, model, api_key, usage=usage):
        print(token, end="", flush=True)
    print(f"Cost: ${usage.cost_usd:.4f}")
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import anthropic

from clusterpilot.cluster.probe import ClusterProbe
from clusterpilot.config import ClusterProfile
from clusterpilot.jobs.env_detect import ScriptEnvironment

_MAX_TOKENS = 2048

# Per-million-token pricing (input, output) by model.
_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6":  (3.00,  15.00),
    "claude-opus-4-6":    (5.00,  25.00),
    "claude-haiku-4-5":   (0.80,   4.00),
}


@dataclass
class ApiUsage:
    """Mutable container for token usage from a single API call."""

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        """Estimated cost in USD based on published per-token pricing."""
        inp_rate, out_rate = _PRICING.get(self.model, (3.00, 15.00))
        return (self.input_tokens * inp_rate + self.output_tokens * out_rate) / 1_000_000


# ── Public API ────────────────────────────────────────────────────────────────

async def generate_script(
    description: str,
    probe: ClusterProbe,
    profile: ClusterProfile,
    model: str,
    api_key: str,
    *,
    api_base_url: str = "",
    partition: str = "",
    script_content: str | None = None,
    driver_script: str | None = None,
    manifest_content: str | None = None,
    extra_files: list[str] | None = None,
    script_env: ScriptEnvironment | None = None,
    usage: ApiUsage | None = None,
) -> AsyncIterator[str]:
    """Stream a SLURM job script token-by-token.

    Args:
        description:    User's plain-language job description.
        probe:          Fresh or cached cluster probe (partitions, modules, account).
        profile:        Cluster connection profile (host, user, account, scratch).
        model:          Model ID, e.g. "claude-sonnet-4-6".
        api_key:        Anthropic API key.
        partition:      Hard partition constraint from the picker. Empty means
                        the model chooses based on the description.
        script_content: Contents of the user's local driver script (Julia, Python,
                        etc.). Included verbatim so the model can inspect imports
                        and infer required modules, GPU count, and walltime.
        driver_script:  Relative path of the driver within the project directory,
                        e.g. "scripts/driver.jl". When set the generated script
                        invokes it as a relative path (the whole project directory
                        is rsynced to the remote job dir). When None, the script is
                        treated as self-contained and invoked by filename only.
        manifest_content: Contents of the project dependency manifest
                        (Project.toml, pyproject.toml, or requirements.txt).
                        Included so the AI can infer the correct runtime version
                        and packages without the user needing to specify them.
        script_env:     Static analysis result from env_detect.analyze_script.
                        Used to generate appropriate environment setup steps
                        (Pkg.instantiate, pip install, etc.) in the script.
        usage:          Optional mutable container; populated with token counts
                        and cost after streaming completes.

    Yields:
        Raw text tokens as they arrive from the API.

    Raises:
        anthropic.APIError: on network or auth failures.
    """
    system = _build_system_prompt(
        probe, profile,
        partition=partition,
        script_content=script_content,
        driver_script=driver_script,
        manifest_content=manifest_content,
        extra_files=extra_files or [],
        script_env=script_env,
    )
    client = anthropic.AsyncAnthropic(
        api_key=api_key,
        base_url=api_base_url or None,
    )

    async with client.messages.stream(
        model=model,
        max_tokens=_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": description}],
    ) as stream:
        async for token in stream.text_stream:
            yield token

        # Populate usage stats after streaming completes.
        if usage is not None:
            final = await stream.get_final_message()
            usage.model = model
            usage.input_tokens = final.usage.input_tokens
            usage.output_tokens = final.usage.output_tokens


# ── System prompt ─────────────────────────────────────────────────────────────

def _build_system_prompt(
    probe: ClusterProbe,
    profile: ClusterProfile,
    *,
    partition: str = "",
    script_content: str | None = None,
    driver_script: str | None = None,
    manifest_content: str | None = None,
    extra_files: list[str] | None = None,
    script_env: ScriptEnvironment | None = None,
) -> str:
    """Construct a cluster-aware system prompt from live probe data."""
    partition_lines = _format_partitions(probe)
    julia_line = ", ".join(probe.julia_versions) or "julia/1.11.3"
    python_line = ", ".join(probe.python_versions) or "(check with: module avail python)"
    account = profile.account or (probe.accounts[0] if probe.accounts else "")
    scratch = profile.expand_scratch()        # ~/... form, for context only
    storage_note = _cluster_storage_note(profile)

    env_setup = _build_env_setup_section(script_env)

    partition_rule = (
        f"The user has selected partition [bold]{partition}[/bold] from the picker. "
        f"You MUST use exactly `--partition={partition}`. Do not change it."
        if partition
        else "Choose the most appropriate partition from the list above based on the job description."
    )

    # The job directory base shown to the AI is for context only — the script
    # must NOT reference it.  All paths must be relative because the submission
    # harness already cd's into the job directory before running sbatch.
    job_dir_note = (
        f"Job working directory: {scratch}/<job-name>/ — the submission harness "
        f"cd's here before sbatch, so the script's CWD is already the job dir."
    )

    manifest_section = ""
    if manifest_content:
        manifest_section = f"""
═══ PROJECT MANIFEST ═══

Use this to infer the correct runtime version and package dependencies.
Match module versions to what is available on this cluster.

```
{manifest_content}
```
"""

    script_section = ""
    if script_content:
        if driver_script:
            intro = (
                f"The user has provided the driver script `{driver_script}` from their "
                f"project package. The entire project directory will be rsynced to the "
                f"remote job directory, so the driver must be invoked as a RELATIVE path: "
                f"`{driver_script}` (not just the filename, and never an absolute path). "
                f"The CWD is already the job directory at runtime, so `{driver_script}` "
                f"will resolve correctly. Do NOT prefix it with ~/ or $HOME/. "
                f"Read it carefully to infer required modules, GPU count, CPU count, "
                f"memory, and walltime."
            )
        else:
            intro = (
                "The user has provided the following script to be run. Read it carefully "
                "to infer required modules, GPU count, CPU count, memory, and walltime. "
                "Load only the modules that are actually needed by this script and "
                "available on this cluster."
            )
        script_section = f"""
═══ USER'S SCRIPT ═══

{intro}

```
{script_content}
```
"""

    if driver_script:
        invoke_line = (
            f"The driver is a relative path within the project — invoke it as: "
            f"julia --project=. {driver_script}"
            if driver_script.endswith(".jl")
            else f"The driver is a relative path within the project — invoke it as: "
            f"python {driver_script}"
            if driver_script.endswith((".py", ".pyw"))
            else f"The driver is a relative path within the project — invoke it: {driver_script}"
        )
    else:
        invoke_line = "The actual job command(s)"

    account_directive = (
        f"   --account        {account}"
        if account
        else "   --account        (omit — this cluster does not require an account)"
    )
    account_rule = (
        f"--account        {account}"
        if account
        else "(no --account directive — not required on this cluster)"
    )

    return f"""\
You generate SLURM job submission scripts for the {profile.name} cluster \
({profile.host}). Output ONLY the bash script — no explanation, no markdown \
fences, no commentary before or after. Start immediately with #!/bin/bash.

═══ CLUSTER FACTS ({profile.name}) ═══

Partitions:
{partition_lines}

Available Julia: {julia_line}
Available Python: {python_line}
User account: {account or "(none configured)"}
{job_dir_note}
{storage_note}
SSH login: {profile.user}@{profile.host}
{manifest_section}{script_section}
═══ SCRIPT RULES ═══

1. Always include these #SBATCH directives:
   --job-name       short, lowercase, no spaces (derived from the description)
   {account_directive}
   --partition      {partition_rule}
   --nodes          usually 1 unless the job explicitly needs multiple
   --ntasks-per-node  match to CPUs needed
   --cpus-per-task  set appropriately for the workload
   --mem             total memory per node, e.g. 32G
   --time           requested walltime as D-HH:MM:SS or HH:MM:SS
   --output         %x-%j.out

   DO NOT include --chdir or -D.  The submission harness already cd's into the
   job directory before running sbatch, so SLURM's default CWD is correct.
   Adding --chdir with ~ breaks on SLURM because ~ is not expanded in #SBATCH
   directives and gets treated as a literal directory name.

   ABSOLUTE RULE FOR --output: write EXACTLY `--output=%x-%j.out` — nothing else.
   Do NOT write a directory path before %x-%j.out.
   Do NOT write `--output=~/.../%x-%j.out`.
   Do NOT write `--output=/home/.../%x-%j.out`.
   The % tokens are relative to the CWD. Any path prefix breaks log discovery.

2. For GPU jobs, add:
   --gres=gpu:<type>:<count>   e.g. gpu:v100:2 for two V100s
   Choose the partition that has the requested GPU type from the partition list above.

3. After #SBATCH directives:
   - module purge
   - module load <required modules>
   - (no cd needed — the CWD is already the job directory)
{env_setup}   - {invoke_line}

   CRITICAL — PATHS IN THE SCRIPT BODY:
   The CWD is already the job directory (set by the submission harness).
   ALL files (scripts, data, outputs) are accessible as RELATIVE paths.
   Use ONLY relative paths.  Examples:
     julia --project=. scripts/run.jl      (NOT ~/clusterpilot_jobs/.../scripts/run.jl)
     python train.py                        (NOT $HOME/.../train.py)
   NEVER use ~/path or $HOME/path or /home/user/path in the script body.
   Bash does NOT expand ~ inside double quotes — it becomes a literal
   directory name, creating broken paths like /job-dir/~/more/path.

   CRITICAL — NO POSITIONAL ARGUMENTS: sbatch does NOT pass $1, $2, $@, etc. when
   submitting with `sbatch script.sh`. These variables are ALWAYS EMPTY at runtime.
   NEVER write `$1`, `$2`, or `$@` anywhere in the script.
   {("The following extra input files have been uploaded to the job directory and MUST be"
     " referenced by their hardcoded relative path — do not use $1 or any variable: "
     + ", ".join(extra_files)) if extra_files else ""}
   {"Hardcode each of these paths directly in the command line." if extra_files else ""}

4. Be conservative with walltime: multiply the user's estimate by 1.3 and
   round up to the nearest hour, but never exceed the partition's time limit.

5. If the user mentions GPU count or type, pick the GPU partition from the list
   above that matches. Use the exact --gres syntax shown for that partition.

6. Do not invent modules. Only load what is available on this cluster.

7. If a script or project manifest was provided above, infer runtime,
   packages, and resource requirements from them rather than guessing.
   Match module versions to those available on this cluster.

8. Version mismatches: when the module version you load differs from what
   the manifest or script requests, add a comment directly above that
   module load line in this exact format:
     # ⚠ VERSION MISMATCH: requested X.Y, loading A.B — <one-line impact assessment>
   Impact assessment guidance:
   - Julia minor version difference (e.g. 1.10 vs 1.11): usually safe, note it
   - Julia major version difference (e.g. 1.6 vs 1.10): likely safe but test first
   - CUDA major version difference (e.g. 11 vs 12): potentially breaking —
     GPU kernels and CUDA.jl/PyTorch may fail; recommend testing with short job
   - CUDA minor version difference: usually safe
   - Python minor version (e.g. 3.10 vs 3.11): usually safe
   - Any module not available on the cluster at all: add a comment:
     # ⚠ MODULE NOT FOUND: <name> — not available on this cluster.
     #   Contact the cluster support team to request installation.
   If all versions match, add no comments.

Output only the script. Begin now.
"""


def _build_env_setup_section(env: ScriptEnvironment | None) -> str:
    """Return environment setup lines to insert in SCRIPT RULES rule 3.

    Returns a string ready for f-string interpolation. Non-empty strings
    always end with a newline so they slot cleanly before the invoke line.
    """
    if env is None:
        return ""

    if env.language == "julia":
        if env.has_manifest:
            # Pinned environment — instantiate exactly what the manifest specifies.
            return "   - julia --project=. -e 'import Pkg; Pkg.instantiate()'\n"
        if env.third_party_imports:
            # No manifest — install inferred packages inline.
            pkgs = "[" + ", ".join(f'"{p}"' for p in env.third_party_imports) + "]"
            return (
                f"   - julia -e 'import Pkg; Pkg.add({pkgs}); Pkg.instantiate()'\n"
                f"     (No Project.toml found — packages inferred from script imports.)\n"
            )

    elif env.language == "python":
        if env.has_manifest:
            # The manifest type is visible in the PROJECT MANIFEST section above.
            return (
                "   - Install Python dependencies from the manifest above.\n"
                "     For requirements.txt: pip install --quiet -r requirements.txt\n"
                "     For pyproject.toml:   pip install --quiet -e .\n"
            )
        if env.third_party_imports:
            imports_str = ", ".join(env.third_party_imports)
            return (
                f"   - pip install --quiet <packages>  where <packages> are the correct\n"
                f"     PyPI names for these imports: {imports_str}\n"
                f"     Apply standard name mappings: sklearn→scikit-learn,\n"
                f"     cv2→opencv-python, PIL→Pillow, skimage→scikit-image.\n"
                f"     Only install what is not already provided by a loaded module.\n"
            )

    return ""


def _cluster_storage_note(profile: ClusterProfile) -> str:
    """Return a one-paragraph storage guidance blurb for the system prompt.

    The blurb is cluster-type-aware so the AI gets correct advice about
    $SCRATCH vs $HOME vs $SLURM_TMPDIR without any cluster-specific names
    being hardcoded elsewhere in the prompt.
    """
    ct = profile.cluster_type
    if ct == "drac":
        return (
            "Storage: ALL job I/O must target $SCRATCH (not $HOME — home quota "
            "is ~50 GB and not meant for job output). $SLURM_TMPDIR is fast local "
            "node SSD; use it for temporary files during the run and copy results "
            "to $SCRATCH before the job ends."
        )
    if ct == "grex":
        return (
            "Storage: this cluster has NO $SCRATCH environment variable. Write job "
            "outputs to the job working directory (relative paths, CWD is already "
            "set by the submission harness) or to $HOME for persistent storage. "
            "$SLURM_TMPDIR is fast local node disk; use it for temporary files "
            "and copy results before the job ends."
        )
    # Generic SLURM cluster — give safe, general advice.
    return (
        "Storage: write job outputs to the working directory using relative paths "
        "(the submission harness has already cd'd into the job directory). "
        "Check this cluster's documentation for the correct path for large "
        "persistent output ($SCRATCH, $WORK, or similar may be available). "
        "Use $SLURM_TMPDIR for temporary files if it is available on this cluster."
    )


def _format_partitions(probe: ClusterProbe) -> str:
    """Format partition table for the system prompt."""
    lines: list[str] = []
    for p in probe.partitions:
        gres = f"  GPUs: {p.gres}" if p.gres else "  (CPU only)"
        default = "  [DEFAULT]" if p.is_default else ""
        lines.append(
            f"  {p.name:<14} nodes={p.nodes:<4} max={p.max_time}{gres}{default}"
        )
    return "\n".join(lines)
