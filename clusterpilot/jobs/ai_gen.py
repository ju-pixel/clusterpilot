"""AI-powered SLURM script generation.

Takes the user's plain-language job description and the cluster probe data,
builds a rich system prompt, then streams a complete sbatch script from the
configured model.

Usage
-----
    async for token in generate_script(description, probe, profile, model, api_key):
        print(token, end="", flush=True)
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import anthropic

from clusterpilot.cluster.probe import ClusterProbe
from clusterpilot.config import ClusterProfile

_MAX_TOKENS = 1024


# ── Public API ────────────────────────────────────────────────────────────────

async def generate_script(
    description: str,
    probe: ClusterProbe,
    profile: ClusterProfile,
    model: str,
    api_key: str,
    *,
    partition: str = "",
    script_content: str | None = None,
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
        script_content: Contents of the user's local script (Julia, Python, etc.).
                        Included verbatim so the model can inspect imports and
                        infer required modules, GPU count, and walltime.

    Yields:
        Raw text tokens as they arrive from the API.

    Raises:
        anthropic.APIError: on network or auth failures.
    """
    system = _build_system_prompt(probe, profile, partition=partition, script_content=script_content)
    client = anthropic.AsyncAnthropic(api_key=api_key)

    async with client.messages.stream(
        model=model,
        max_tokens=_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": description}],
    ) as stream:
        async for token in stream.text_stream:
            yield token


# ── System prompt ─────────────────────────────────────────────────────────────

def _build_system_prompt(
    probe: ClusterProbe,
    profile: ClusterProfile,
    *,
    partition: str = "",
    script_content: str | None = None,
) -> str:
    """Construct a cluster-aware system prompt from live probe data."""
    partition_lines = _format_partitions(probe)
    julia_line = ", ".join(probe.julia_versions) or "julia/1.11.3"
    account = profile.account or (probe.accounts[0] if probe.accounts else "")
    scratch = profile.expand_scratch()

    partition_rule = (
        f"The user has selected partition [bold]{partition}[/bold] from the picker. "
        f"You MUST use exactly `--partition={partition}`. Do not change it."
        if partition
        else "Choose the most appropriate partition from the list above based on the job description."
    )

    script_section = ""
    if script_content:
        script_section = f"""
═══ USER'S SCRIPT ═══

The user has provided the following script to be run. Read it carefully to
infer required modules, GPU count, CPU count, memory, and walltime. Load
only the modules that are actually needed by this script and available on
this cluster.

```
{script_content}
```
"""

    return f"""\
You generate SLURM job submission scripts for the {profile.name} cluster \
({profile.host}). Output ONLY the bash script — no explanation, no markdown \
fences, no commentary before or after. Start immediately with #!/bin/bash.

═══ CLUSTER FACTS ({profile.name}) ═══

Partitions:
{partition_lines}

Available Julia: {julia_line}
User account: {account}
Job working directory base: {scratch}

SSH login: {profile.user}@{profile.host}
{script_section}
═══ SCRIPT RULES ═══

1. Always include these #SBATCH directives:
   --job-name       short, lowercase, no spaces (derived from the description)
   --account        {account}
   --partition      {partition_rule}
   --nodes          usually 1 unless the job explicitly needs multiple
   --ntasks-per-node  match to CPUs needed
   --cpus-per-task  set appropriately for the workload
   --mem             total memory per node, e.g. 32G
   --time           requested walltime as D-HH:MM:SS or HH:MM:SS
   --output         always use %x-%j.out  (required for log discovery)

2. For GPU jobs, add:
   --gres=gpu:<type>:<count>   e.g. gpu:v100:2 for two V100s on stamps
   Choose the partition that has the requested GPU type.

3. After #SBATCH directives:
   - module purge
   - module load <required modules>
   - cd {scratch}/$SLURM_JOB_NAME
   - The actual job command(s)

4. Be conservative with walltime: multiply the user's estimate by 1.3 and
   round up to the nearest hour, but never exceed the partition's time limit.

5. If the user mentions GPU count or type, pick the partition that has it.
   Prefer stamps over stamps-b unless the user asks for shorter queue.
   Prefer lgpu (L40S) for inference or memory-bandwidth workloads.

6. Do not invent modules. Only load what is available on this cluster.

7. If a script was provided above, infer resource requirements from it
   rather than guessing. Match module versions to those available on
   this cluster.

Output only the script. Begin now.
"""


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
