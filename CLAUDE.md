# ClusterPilot

AI-assisted HPC job workflow manager for SLURM-based clusters.

## Project Overview

ClusterPilot is a Python terminal application (Textual TUI) that helps HPC researchers:
1. Describe jobs in plain language → Claude generates correct SLURM scripts
2. Upload files and submit jobs via SSH to configured clusters
3. Monitor job status without persistent connections (SSH ControlMaster + poll daemon)
4. Auto-sync results and receive push notifications on job events (ntfy.sh)

**Target clusters:** UManitoba Grex (v0.1 MVP), Compute Canada cedar/narval (post-v1)
**Business model:** Open-source self-hosted; future hosted tier (API key managed by dev) with free/paid tiers, ntfy.sh-style.

## Tech Stack

- **Python ≥ 3.9** — core runtime (user currently on 3.9.6)
- **Textual** — terminal UI framework (amber phosphor theme, see design files)
- **Anthropic Python SDK** — Claude API for SLURM script generation
- **httpx** — async HTTP for ntfy.sh push notifications
- **aiosqlite** — async SQLite for local job history/metadata
- **subprocess + asyncio** — wraps system `ssh`, `rsync`, `sbatch`, `squeue`, `sinfo`
- **tomli/tomllib** — TOML config (`tomllib` stdlib ≥ 3.11, else `tomli` package)

Do NOT use paramiko or asyncssh — we wrap the system SSH client to leverage ControlMaster.

## Module Structure

```
clusterpilot/
├── __main__.py           # CLI entry point: `clusterpilot` command
├── app.py                # top-level Textual App, mounts screens
├── config.py             # config.toml loading, ClusterProfile dataclass
├── db.py                 # SQLite: job history, run metadata
├── cluster/
│   ├── __init__.py
│   ├── probe.py          # run sinfo, module avail, sacctmgr; cache 24h to disk
│   └── slurm.py          # sbatch submit, squeue poll, scancel
├── ssh/
│   ├── __init__.py
│   ├── connection.py     # ControlMaster setup, run_remote(cluster, cmd) → str
│   └── rsync.py          # rsync upload/download wrappers
├── jobs/
│   ├── __init__.py
│   ├── ai_gen.py         # build Claude prompt with cluster context, stream response
│   └── daemon.py         # async poll loop: embedded or standalone or systemd
├── notify/
│   ├── __init__.py
│   └── ntfy.py           # ntfy.sh HTTP push notifications
└── tui/
    ├── __init__.py
    ├── jobs_view.py      # F1: job list + detail + output log tail
    ├── submit_view.py    # F2: job description → script gen → upload → submit
    └── config_view.py    # F9: cluster profiles, SSH, model, notification settings
```

## SSH Strategy: ControlMaster

On first connect, user authenticates once. All subsequent `ssh`/`rsync`/`sftp` reuse the socket — sub-second, no repeated auth. Survives laptop sleep and network changes (until ControlPersist expires).

ClusterPilot writes to `~/.ssh/config.d/clusterpilot-<cluster>.conf` (ensure `~/.ssh/config` contains `Include ~/.ssh/config.d/*.conf`):

```
Host grex.hpc.umanitoba.ca
  ControlMaster auto
  ControlPath ~/.ssh/cm_%h_%p_%r
  ControlPersist 4h
  ServerAliveInterval 60
```

`ssh/connection.py` exports:
- `ensure_connected(cluster)` — checks socket with `ssh -O check`; opens new connection if none
- `run_remote(cluster, cmd) -> str` — asyncio subprocess wrapping `ssh <host> <cmd>`
- `open_interactive(cluster)` — for log tailing / initial setup

## AI Script Generation (`jobs/ai_gen.py`)

1. Load cluster probe cache: partitions, available modules, account/QOS limits
2. Build system prompt with full cluster context (from `cluster/probe.py`)
3. Call Claude with user's plain-language description (streaming)
4. Yield tokens to TUI for typewriter effect
5. User reviews/edits script before any sbatch is run

Model is user-configurable: `claude-sonnet-4-6` default. User can set `claude-opus-4-6` in config for better quality on complex jobs. For error diagnosis (future feature), prefer Opus.

## Configuration File

`~/.config/clusterpilot/config.toml`:

```toml
[defaults]
model = "claude-sonnet-4-6"
api_key = ""          # or set ANTHROPIC_API_KEY env var
poll_interval = 300   # seconds

[[clusters]]
name = "grex"
host = "yak.hpc.umanitoba.ca"
user = "juliaf"
account = "def-stamps"
scratch = "$HOME/clusterpilot_jobs"   # Grex: no separate $SCRATCH, home is 15T NFS

[[clusters]]
name = "cedar"
host = "cedar.computecanada.ca"
user = "YOUR_USERNAME"
account = "def-yoursupervisor"
scratch = "$SCRATCH"

[notifications]
backend = "ntfy"
ntfy_topic = ""
ntfy_server = "https://ntfy.sh"
```

## Poll Daemon (`jobs/daemon.py`)

Async loop, three modes:
- **Embedded**: runs in background within TUI process
- **Standalone**: `clusterpilot daemon run` (keeps running after TUI closes)
- **systemd**: `clusterpilot daemon install` writes `~/.config/systemd/user/clusterpilot-poll.service`

Every `poll_interval` seconds per tracked job:
1. `run_remote(cluster, "squeue -j JOB_ID -h -o '%T'")` → status string
2. COMPLETED → `rsync.pull()` → `notify()`
3. FAILED → fetch slurm-JOB.out tail → `notify()` with excerpt
4. RUNNING → update ETA estimate in DB; notify if approaching time limit

## Cluster Notes

**Grex (UManitoba)** — v0.1 target:
- Host: `yak.hpc.umanitoba.ca` (login: `juliaf@yak.hpc.umanitoba.ca`)
- Account: `def-stamps`
- Scheduler: SLURM
- Partitions (confirmed via sinfo):
  - CPU: `skylake`* (default, 43 nodes, 21d), `genoa` (27 nodes), `largemem` (12 nodes), `genlm`, `chrim`, `chrimlm`, `genoacpu-b` (7d), `mcordcpu`, `pgs`, `test` (23h)
  - GPU: `gpu` (V100×4, 7d, 2 nodes), `stamps`/`stamps-b` (V100×4, 21d/7d, 3 nodes), `lgpu` (L40S×2, 3d), `agro`/`agro-b` (A30×2), `livi`/`livi-b` (V100×16), `mcordgpu`/`mcordgpu-b` (A30×4)
  - GRES syntax for sbatch: `--gres=gpu:v100:2` (for V100), `--gres=gpu:l40s:1` (for L40S), etc.
- Module system: Lmod — Julia available: `julia/1.10.3`, `julia/1.11.3` (default)
- Storage: no separate `$SCRATCH`; home IS the large filesystem (15T NFS). Job working dirs live under `$HOME/clusterpilot_jobs/<jobname>/`

**Compute Canada cedar/narval** — post-v0.1:
- Hosts: `cedar.computecanada.ca`, `narval.computecanada.ca`
- Accounts: `def-supervisor` format
- Storage: `$SCRATCH`

## Design Reference Files (not deployed)

- `hpc-app-flow.jsx` — Workflow, architecture, and UI mockup documentation (React)
- `clusterpilot-tui.jsx` — Amber phosphor TUI design reference (React)

The Textual UI implements the aesthetic from these files: amber/green on near-black (`#0c0a06`), box-drawing borders, phosphor glow via Textual CSS. Colors from `clusterpilot-tui.jsx` constant `P` are authoritative.

## Key Conventions

- **Async everywhere**: asyncio + Textual's async model. No blocking calls on the event loop.
- **Type annotations** on all public functions and dataclasses.
- **Dependency injection**: `ClusterProfile` and `Config` passed as arguments, not globals.
- **SSH abstraction**: ALL remote commands go through `ssh/connection.py:run_remote()`. Never raw subprocess inline elsewhere.
- **State-before-action**: All job state written to SQLite before any side effect (submit, rsync).
- **Probe cache**: Cluster probe results cached to `~/.cache/clusterpilot/<cluster>/probe.json` with 24h TTL. Always check cache before SSH call.
- **No hardcoded credentials**: usernames, accounts, API keys always come from config or env vars.

## Development Commands

```bash
pip install -e ".[dev]"   # install with dev deps
clusterpilot              # launch TUI
clusterpilot daemon run   # run poll daemon in foreground
pytest                    # run tests
ruff check .              # lint
```
