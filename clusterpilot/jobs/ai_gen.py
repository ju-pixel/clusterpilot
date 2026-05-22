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

import json

import anthropic
import httpx
import openai

from clusterpilot.cluster.probe import ClusterProbe
from clusterpilot.config import ClusterProfile
from clusterpilot.jobs.env_detect import ScriptEnvironment

_MAX_TOKENS = 2048

# Per-million-token pricing (input, output) by model.
# Unknown models (e.g. local Ollama) default to (0, 0).
_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-sonnet-4-6":  (3.00,  15.00),
    "claude-opus-4-6":    (5.00,  25.00),
    "claude-haiku-4-5":   (0.80,   4.00),
    # OpenAI
    "gpt-4o":             (2.50,  10.00),
    "gpt-4o-mini":        (0.15,   0.60),
    "o4-mini":            (1.10,   4.40),
    "gpt-4-turbo":       (10.00,  30.00),
}


@dataclass
class ApiUsage:
    """Mutable container for token usage from a single API call."""

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        """Estimated cost in USD based on published per-token pricing.

        Returns 0.0 for unknown models (e.g. local Ollama models).
        """
        inp_rate, out_rate = _PRICING.get(self.model, (0.00, 0.00))
        return (self.input_tokens * inp_rate + self.output_tokens * out_rate) / 1_000_000


# ── Public API ────────────────────────────────────────────────────────────────

async def generate_script(
    description: str,
    probe: ClusterProbe,
    profile: ClusterProfile,
    model: str,
    api_key: str,
    *,
    provider: str = "anthropic",
    api_base_url: str = "",
    partition: str = "",
    array_spec: str = "",
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
        array_spec=array_spec,
        script_content=script_content,
        driver_script=driver_script,
        manifest_content=manifest_content,
        extra_files=extra_files or [],
        script_env=script_env,
    )

    if provider == "anthropic":
        # When routing through the CP proxy, bypass the Anthropic SDK and parse
        # SSE events directly — the SDK's internal state machine breaks on proxied responses.
        if api_base_url and "/proxy" in api_base_url:
            async for token in _stream_proxy(system, description, model, api_key, api_base_url, usage):
                yield token
        else:
            async for token in _stream_anthropic(system, description, model, api_key, api_base_url, usage):
                yield token
    else:
        # "openai" and "ollama" both use the OpenAI-compatible API.
        effective_base_url = api_base_url or (
            "http://localhost:11434/v1" if provider == "ollama" else None
        )
        effective_key = api_key or ("ollama" if provider == "ollama" else "")
        async for token in _stream_openai(system, description, model, effective_key, effective_base_url, usage):
            yield token


# ── Provider streaming helpers ────────────────────────────────────────────────

async def _stream_anthropic(
    system: str,
    description: str,
    model: str,
    api_key: str,
    api_base_url: str,
    usage: ApiUsage | None,
) -> AsyncIterator[str]:
    client = anthropic.AsyncAnthropic(api_key=api_key, base_url=api_base_url or None)
    async with client.messages.stream(
        model=model,
        max_tokens=_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": description}],
    ) as stream:
        async for token in stream.text_stream:
            yield token
        if usage is not None:
            try:
                final = await stream.get_final_message()
                usage.model = model
                usage.input_tokens = final.usage.input_tokens
                usage.output_tokens = final.usage.output_tokens
            except Exception:
                usage.model = model  # tokens stay 0 — not fatal


async def _stream_proxy(
    system: str,
    description: str,
    model: str,
    api_key: str,
    api_base_url: str,
    usage: ApiUsage | None,
) -> AsyncIterator[str]:
    """Generate via the ClusterPilot hosted proxy using a single non-streaming call.

    Uses /proxy/generate (non-SSE) to avoid Fly.io response-buffering issues with
    text/event-stream. Yields the full text in small chunks to keep the TUI display
    updating progressively.
    """
    url = api_base_url.rstrip("/") + "/generate"
    payload = {
        "model": model,
        "max_tokens": _MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": description}],
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={"x-api-key": api_key},
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Proxy returned HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    text: str = data.get("text", "")
    if usage is not None:
        usage.model = model
        usage.input_tokens = data.get("input_tokens", 0)
        usage.output_tokens = data.get("output_tokens", 0)

    # Yield in small chunks so the script panel updates progressively.
    chunk_size = 40
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]


async def _stream_openai(
    system: str,
    description: str,
    model: str,
    api_key: str,
    api_base_url: str | None,
    usage: ApiUsage | None,
) -> AsyncIterator[str]:
    client = openai.AsyncOpenAI(api_key=api_key, base_url=api_base_url or None)
    stream = await client.chat.completions.create(
        model=model,
        max_tokens=_MAX_TOKENS,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": description},
        ],
        stream=True,
        stream_options={"include_usage": True},
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
        if usage is not None and chunk.usage is not None:
            usage.model = model
            usage.input_tokens = chunk.usage.prompt_tokens
            usage.output_tokens = chunk.usage.completion_tokens


# ── System prompt ─────────────────────────────────────────────────────────────

def _build_system_prompt(
    probe: ClusterProbe,
    profile: ClusterProfile,
    *,
    partition: str = "",
    array_spec: str = "",
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
    storage_note = _cluster_storage_note(profile, probe)

    is_drac = profile.cluster_type == "drac"
    is_grex = profile.cluster_type == "grex"

    env_setup = _build_env_setup_section(script_env, is_drac=is_drac)

    # On DRAC (Alliance Canada: Narval, Cedar, Beluga, Graham) the partition is
    # not a user-facing concept — the scheduler routes jobs by --account, --gres,
    # --time and --mem. Emitting --partition= against a probed partition name
    # makes sbatch reject the job. The picked partition is reused as a GRES /
    # walltime hint instead. See CLAUDE.md "Partition selection".
    selected_partition_gres = ""
    selected_partition_max_time = ""
    if partition:
        match = next((p for p in probe.partitions if p.name == partition), None)
        if match is not None:
            selected_partition_gres = match.gres
            selected_partition_max_time = match.max_time

    if is_drac:
        partition_directive_line = ""
        hint_block = ""
        if partition:
            gres_hint = (
                f"  - GRES to use: `{selected_partition_gres}` "
                "(match this exactly in your --gres line)\n"
                if selected_partition_gres
                else "  - This partition is CPU-only — do not emit --gres.\n"
            )
            walltime_hint = (
                f"  - Walltime ceiling: {selected_partition_max_time} "
                "(your --time must not exceed this)\n"
                if selected_partition_max_time
                else ""
            )
            hint_block = (
                f"\nThe user picked partition `{partition}` from the TUI as a "
                f"routing hint:\n{gres_hint}{walltime_hint}"
            )
        drac_scheduling_note = (
            "═══ DRAC SCHEDULING ═══\n\n"
            "This is an Alliance Canada (DRAC) cluster. DO NOT emit "
            "`#SBATCH --partition=` in the script. DRAC has no user-facing "
            "partition selection; the scheduler routes the job automatically "
            "based on --account, --gres, --time, --mem, and node count. "
            "Emitting --partition= against any probed partition name will be "
            "rejected by sbatch."
            f"{hint_block}\n"
        )
        partition_rule = ""   # unused on DRAC, kept for f-string symmetry
    else:
        drac_scheduling_note = ""
        partition_rule = (
            f"The user has selected partition [bold]{partition}[/bold] from the picker. "
            f"You MUST use exactly `--partition={partition}`. Do not change it."
            if partition
            else "Choose the most appropriate partition from the list above based on the job description."
        )
        partition_directive_line = f"   --partition      {partition_rule}\n"

    # The job directory base shown to the AI is for context only — the script
    # must NOT reference it.  All paths must be relative because the submission
    # harness already cd's into the job directory before running sbatch.
    job_dir_note = (
        f"Job working directory: {scratch}/<job-name>/ — the submission harness "
        f"cd's here before sbatch, so the script's CWD is already the job dir."
    )

    # Build array rule block outside the main f-string (Python 3.9 nested f-string limits).
    if array_spec:
        output_rule = (
            f"This is a job array (--array={array_spec}). Write EXACTLY "
            "`--output=%x-%A-%a.out`. %A is the array master job ID, %a is the task "
            "index — each task gets its own log. Do NOT use %j for array jobs."
        )
        array_rule = (
            f"2. JOB ARRAY — the user has requested an array with spec [{array_spec}]:\n"
            f"   Add `--array={array_spec}` to the #SBATCH directives.\n"
            "   Use `$SLURM_ARRAY_TASK_ID` in the script body to select parameters for each task.\n"
            "   Each task gets its own output log because --output uses %A and %a (see rule 1).\n"
            "   CRITICAL: the array spec is a hard constraint — use it exactly as given.\n"
            "   Do NOT change it. Do NOT use a different range or step.\n\n"
        )
    else:
        output_rule = "Write EXACTLY `--output=%x-%j.out` — nothing else."
        array_rule = ""

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

    # Detect GPU libraries in the driver script's imports so we can force the
    # AI to emit --gres. Without this, a job whose driver `import`s CUDA but
    # whose description doesn't mention "GPU" silently gets a CPU-only script,
    # the DRAC scheduler routes it to a CPU node, and the runtime dies on
    # `CUDA.device()` with "CUDA driver not functional" (Narval 2026-05-21).
    gpu_libs = _detect_gpu_libraries(script_env)
    if gpu_libs:
        if is_drac:
            gpu_default_gres = selected_partition_gres or "gpu:a100:1"
        elif is_grex:
            # Grex's submit_filter.lua rejects --gres=gpu:<type>:<count> on
            # some partitions (notably lgpu) — it expands the partition list to
            # include the user's default CPU partition and then errors out on
            # "lgpu is meant for GPU jobs only". Bare gpu:N dodges this path.
            gpu_default_gres = "gpu:1"
        else:
            gpu_default_gres = "gpu:<type>:<count>"
        grex_type_note = (
            " On Grex, use the type-less form `--gres=gpu:N` by default. Only "
            "include the type subspec (e.g. `gpu:v100:1`, `gpu:l40s:1`) if the "
            "user's description explicitly requests a specific GPU type — Grex's "
            "submit filter rejects type subspec on some partitions otherwise."
            if is_grex
            else ""
        )
        # DRAC + CUDA: the cuda module provides libcudart and friends on
        # LD_LIBRARY_PATH for CUDA.jl in local_toolkit mode at runtime.
        # ClusterPilot's preflight separately writes LocalPreferences.toml
        # with `local_toolkit = true, version = "12.2"`. The module load below
        # pins the matching toolkit version.
        drac_cuda_note = (
            "\n\nThis is a DRAC cluster and the driver uses CUDA. After "
            "`module load julia/<version>`, you MUST also emit "
            "`module load cuda/12.2` (default on Narval; pin to match "
            "LocalPreferences.toml). Without it the CUDA toolkit libraries "
            "(libcudart, libnvrtc, ...) may not be on LD_LIBRARY_PATH and "
            "CUDA.jl can fail at runtime even with --gres=gpu set."
            if is_drac and "CUDA" in gpu_libs
            else ""
        )
        gpu_directive_block = (
            f"\n═══ GPU REQUIRED ═══\n\n"
            f"The driver script imports {', '.join(gpu_libs)}, which requires "
            f"a GPU at runtime. You MUST emit `#SBATCH --gres={gpu_default_gres}` "
            f"in the directive block. Omitting --gres routes the job to a CPU "
            f"node and the runtime will crash with 'CUDA driver not functional' "
            f"or equivalent. If the user's description specifies a GPU count or "
            f"type, use that; otherwise use the GRES shown above.{grex_type_note}{drac_cuda_note}\n"
        )
    else:
        gpu_directive_block = ""

    # Rule 3's `module purge` line is only useful on generic clusters where
    # the base environment is unknown. On DRAC, StdEnv/2023 is sticky and a
    # regular `module purge` cannot unload it — it just emits a noisy
    # "The following modules were not unloaded" warning in every job log.
    # Same on Grex with SBEnv. Drop the line on both.
    module_purge_line = (
        "   - module purge\n"
        if not (is_drac or is_grex)
        else ""
    )

    # Rule 2 (GPU GRES guidance for the general case — no detected GPU import).
    # Grex's submit filter behaviour means even the general rule should prefer
    # the type-less form there.
    if is_grex:
        gpu_rule_2 = (
            "2. For GPU jobs, add:\n"
            "   --gres=gpu:<count>          e.g. gpu:1 — bare form is the safe default on Grex\n"
            "   Only include a type subspec (gpu:v100:N, gpu:l40s:N, gpu:a30:N, ...) when\n"
            "   the user EXPLICITLY names a GPU type. Grex's submit filter rejects the\n"
            "   type subspec on some partitions (lgpu in particular).\n"
            "   Choose a partition that has the GPU type the user asked for (if any)."
        )
    else:
        gpu_rule_2 = (
            "2. For GPU jobs, add:\n"
            "   --gres=gpu:<type>:<count>   e.g. gpu:v100:2 for two V100s\n"
            "   Choose the partition that has the requested GPU type from the partition list above."
        )

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
{manifest_section}{script_section}{drac_scheduling_note}{gpu_directive_block}
═══ SCRIPT RULES ═══

1. Always include these #SBATCH directives:
   --job-name       short, lowercase, no spaces (derived from the description)
   {account_directive}
{partition_directive_line}   --nodes          usually 1 unless the job explicitly needs multiple
   --ntasks-per-node  match to CPUs needed
   --cpus-per-task  set appropriately for the workload
   --mem             total memory per node, e.g. 32G
   --time           requested walltime as D-HH:MM:SS or HH:MM:SS
   --output         %x-%j.out

   DO NOT include --chdir or -D.  The submission harness already cd's into the
   job directory before running sbatch, so SLURM's default CWD is correct.
   Adding --chdir with ~ breaks on SLURM because ~ is not expanded in #SBATCH
   directives and gets treated as a literal directory name.

   ABSOLUTE RULE FOR --output:
   {output_rule}
   Do NOT write a directory path before the % tokens.
   Do NOT write `--output=~/.../%x-...`.
   Do NOT write `--output=/home/.../%x-...`.
   The % tokens are relative to the CWD. Any path prefix breaks log discovery.

{array_rule}{gpu_rule_2}

3. After #SBATCH directives:
{module_purge_line}   - module load <required modules>
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


def _build_env_setup_section(
    env: ScriptEnvironment | None,
    *,
    is_drac: bool = False,
) -> str:
    """Return environment setup lines to insert in SCRIPT RULES rule 3.

    Returns a string ready for f-string interpolation. Non-empty strings
    always end with a newline so they slot cleanly before the invoke line.

    On DRAC clusters the depot is pre-warmed on the login node by
    :func:`clusterpilot.jobs.preflight.warm_depot` before sbatch runs, so the
    compute-node script must set ``JULIA_PKG_OFFLINE=true`` to skip the
    registry-update network call. The ``Pkg.instantiate()`` line is kept for
    idempotency (no-op against a warm offline depot).
    """
    if env is None:
        return ""

    julia_offline_prefix = (
        "   - export JULIA_PKG_OFFLINE=true   "
        "# depot pre-warmed on login node — skip the registry network update\n"
        if is_drac
        else ""
    )

    if env.language == "julia":
        if env.has_manifest:
            # Pinned environment — instantiate exactly what the manifest specifies.
            return (
                f"{julia_offline_prefix}"
                "   - julia --project=. -e 'import Pkg; Pkg.instantiate()'\n"
            )
        if env.third_party_imports:
            # No manifest — install inferred packages inline.
            pkgs = "[" + ", ".join(f'"{p}"' for p in env.third_party_imports) + "]"
            return (
                f"{julia_offline_prefix}"
                f"   - julia -e 'import Pkg; Pkg.add({pkgs}); Pkg.instantiate()'\n"
                f"     (No Project.toml found — packages inferred from script imports.)\n"
            )

    elif env.language == "python":
        if is_drac:
            # DRAC compute nodes have no internet. ClusterPilot's preflight
            # has already run `pip install --user` on the login node; the
            # packages are in ~/.local/lib/python3.X/site-packages/ and the
            # NFS-shared $HOME makes them visible on the compute node. The
            # AI must NOT add a pip install line to the script.
            return (
                "   - # Python dependencies were pre-installed on the login node by\n"
                "     # ClusterPilot's preflight (DRAC compute nodes have no internet).\n"
                "     # DO NOT emit any `pip install` line in this script.\n"
            )
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


def _cluster_storage_note(profile: ClusterProfile, probe: ClusterProbe) -> str:
    """Return storage guidance for the system prompt.

    Uses the probed $SCRATCH value to give accurate advice for any cluster.
    cluster_type = "drac" adds a hard policy warning on top of the probe result
    (DRAC home quota is ~50 GB — jobs writing there get quota-killed).
    All other cluster types are handled by probed $SCRATCH presence alone.
    """
    scratch = probe.scratch_env   # non-empty if $SCRATCH is set on the cluster

    if profile.cluster_type == "drac":
        # DRAC has a hard policy: $SCRATCH is mandatory regardless of size.
        dest = scratch or "$SCRATCH"
        return (
            f"Storage: ALL job I/O must target $SCRATCH ({dest}) — NEVER $HOME. "
            "Home quota on DRAC is ~50 GB and jobs writing there will be killed "
            "by quota. $SLURM_TMPDIR is fast local node SSD; use it for temporary "
            f"files and copy results to {dest} before the job ends."
        )

    if scratch:
        # Cluster has $SCRATCH — probed directly, no guessing needed.
        return (
            f"Storage: this cluster has $SCRATCH at {scratch}. "
            "Prefer $SCRATCH over $HOME for large job output. "
            "$SLURM_TMPDIR is fast local node disk; use it for temporary files "
            f"and copy results to {scratch} before the job ends."
        )

    # No $SCRATCH on this cluster — use job working directory / $HOME.
    return (
        "Storage: this cluster has no $SCRATCH environment variable. "
        "Write job outputs to the job working directory (relative paths — "
        "the submission harness has already cd'd into the job directory) "
        "or to $HOME for persistent storage. "
        "Use $SLURM_TMPDIR for temporary files if available on this cluster."
    )


# Top-level package names whose presence in a driver script means a GPU is
# required at runtime. Triggers a hard `#SBATCH --gres=...` directive in the
# generated script even if the user's description doesn't mention "GPU".
_GPU_LIBRARIES: frozenset[str] = frozenset({
    # Julia
    "CUDA", "AMDGPU", "oneAPI", "Metal", "KernelAbstractions",
    # Python
    "torch", "jax", "cupy", "tensorflow", "cudf", "cuml", "cugraph",
    "pycuda", "numba",
})


def _detect_gpu_libraries(env: ScriptEnvironment | None) -> list[str]:
    """Return the GPU-library imports detected in the driver script, sorted."""
    if env is None or not env.third_party_imports:
        return []
    return sorted(set(env.third_party_imports) & _GPU_LIBRARIES)


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
