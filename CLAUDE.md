# ClusterPilot

AI-assisted HPC workflow manager for Compute Canada (DRAC) clusters
and University of Manitoba's Grex cluster.
Built by a computational physics PhD student who got tired of doing this manually.

---

## What this does

Automates the full local-to-cluster-and-back workflow for researchers on
supported HPC clusters:

1. SSH authentication via ControlMaster (one interactive login, then headless)
2. Cluster environment discovery (sinfo, module avail, sacctmgr)
3. AI-generated SLURM scripts via the Anthropic API, contextualised to the
   specific cluster's partitions, modules, accounts, and quirks
4. File upload to the appropriate scratch/work filesystem via rsync
5. Job submission and SQLite-backed job tracking
6. Background poll daemon (systemd user service) -- polls squeue every 5 min,
   no persistent SSH connection required
7. Push notifications to phone on job events (started, completed, failed, ETA)
8. Automatic result sync back to local workstation on job completion

---

## Supported clusters

### 1. Compute Canada / DRAC national clusters

cedar, narval, graham, beluga.
Docs: https://docs.alliancecan.ca/wiki/Getting_started

**DRAC-specific SLURM quirks -- inject into every generation prompt:**

- `--account=def-supervisorname` is mandatory in every script; the job will
  be rejected without it
- Job I/O must target `$SCRATCH`, never `$HOME` (home quota is ~50 GB;
  scratch is a large fast parallel filesystem)
- Module system is Lmod: `module load julia/1.10.4 cuda/12.2`
- Use `module spider <name>` to find available versions
- GPU syntax on cedar/narval: `--gres=gpu:a100:2`
- `$SLURM_TMPDIR` is fast local node-level SSD; use for temporary files
  during a run, copy results to `$SCRATCH` before job ends
- Email notifications: `--mail-type=FAIL,END` and `--mail-user=`
- Array jobs: `--array=0-N%M` (M = max simultaneous)
- GPU walltime limits: 24h on cedar gpu partition, 48h on narval gpu partition
- Always `module purge` before loading new modules to avoid conflicts

**DRAC scratch path:**
```
$SCRATCH  ->  /scratch/<username>/
```

---

### 2. University of Manitoba -- Grex

Grex is a community HPC cluster at UManitoba, running SLURM. Available to
UManitoba-affiliated researchers and their collaborators. It is a heterogeneous
cluster with contributed nodes, large-memory nodes, and GPU nodes.
Docs: https://um-grex.github.io/grex-docs/

**Login:**
- Hostname: `grex.hpc.umanitoba.ca`
- Login nodes: `bison.hpc.umanitoba.ca`, `yak.hpc.umanitoba.ca`
  (tatanka and zebu were decommissioned August-September 2024 -- never use)
- MFA is required
- SSH access works from off-campus without VPN; VPN is only needed for
  the OpenOnDemand web interface (ood.hpc.umanitoba.ca)

**Grex-specific SLURM quirks -- inject into every generation prompt:**

- `--account=` is NOT mandatory on Grex the way it is on DRAC; most users
  submit to the community pool without specifying an account
- Partitions must always be specified explicitly; the app handles this via the
  partition picker on the F2 Submit screen (populated from sinfo cache)
- The only SLURM default on Grex is `skylake` for non-contributor CPU jobs;
  the app should not rely on this -- the picker makes selection explicit always
- GPU jobs MUST use a GPU partition; requesting `--gres=gpu:...` on `skylake`,
  `compute`, or `largemem` will cause the job to be rejected by SLURM
- Multiple partitions can be listed: `--partition=skylake,largemem` so SLURM
  picks whichever is free first; useful for CPU jobs that fit either
- `$SLURM_TMPDIR` is fast local node disk; use for temp I/O, copy results
  to `$HOME` or group project storage before the job ends
- Grex does NOT have a `$SCRATCH` environment variable like DRAC; the
  equivalent is `$HOME` (for smaller data) or a group project directory
- Contributed/community nodes: non-owner jobs run opportunistically and may
  be preempted; do not use these partitions for long uncheckpointed runs
  unless you own them
- Module system is Lmod, same syntax as DRAC: `module load <name>/<version>`
- CVMFS is available as an additional software stack source

**Grex partitions (inject relevant rows per job type):**

| Partition  | Use case                       | Notes                                    |
|------------|--------------------------------|------------------------------------------|
| skylake    | Default short CPU jobs         | Intel Skylake; auto-default for most users |
| largemem   | High-memory CPU jobs           | Must specify explicitly                  |
| compute    | General CPU                    | Must specify explicitly                  |
| gpu        | GPU jobs                       | Must specify; L40S and older GPU nodes   |
| test       | Short interactive/test jobs    | Oversubscription enabled; quick turnaround |
| stamps-b   | Contributed (owner priority)   | Opportunistic for non-owners             |

**Grex hardware (as of early 2025):**
- AMD Genoa CPU nodes: 30 nodes added September 2024, 5760 total cores
- GPU nodes: 2 nodes with NVIDIA L40S GPUs added 2025
- GPU syntax: `--gres=gpu:l40s:1` (L40S nodes) or `--gres=gpu:1` (older nodes)

**Grex storage:**
```
$HOME            ->  /home/<username>/           (personal, limited quota)
$SLURM_TMPDIR   ->  fast local node disk         (vanishes when job ends)
group project    ->  /home/grex/<group>/          (shared group storage)
```
There is no `$SCRATCH` on Grex. Write job outputs to `$HOME` or the group
project directory. Use `$SLURM_TMPDIR` only for within-job temporary files.

---

## Cluster type abstraction

The `cluster_type` field in the config drives which quirks are injected into
SLURM generation prompts. Adding a new institution means adding a new type
in `cluster/profiles.py` -- cluster-specific logic lives in one place only.

```toml
# Example entries in ~/.config/clusterpilot/config.toml

[[clusters]]
name = "cedar"
hostname = "cedar.computecanada.ca"
username = "jfrank"
account = "def-mlafond"        # mandatory for DRAC
ssh_key = "~/.ssh/id_ed25519"
scratch_path = "/scratch/jfrank"
cluster_type = "drac"

[[clusters]]
name = "narval"
hostname = "narval.computecanada.ca"
username = "jfrank"
account = "def-mlafond"
ssh_key = "~/.ssh/id_ed25519"
scratch_path = "/scratch/jfrank"
cluster_type = "drac"

[[clusters]]
name = "grex"
hostname = "grex.hpc.umanitoba.ca"
username = "jfrank"
account = ""                   # not required on Grex
ssh_key = "~/.ssh/id_ed25519"
scratch_path = "/home/jfrank"  # or group project path; no $SCRATCH on Grex
cluster_type = "grex"
```

---

## Stack

- **Language:** Python 3.11+
- **TUI:** Textual (terminal UI framework)
- **SSH:** subprocess + system ssh binary with ControlMaster (not Paramiko)
- **AI:** Anthropic Python SDK, claude-sonnet-4-6 for SLURM generation
- **Database:** SQLite via stdlib sqlite3 (zero-dependency local job history)
- **Notifications:** ntfy.sh (or any HTTP POST endpoint) via httpx
- **Daemon:** systemd user service (clusterpilot-poll.service)
- **Config:** TOML via stdlib tomllib / tomli

---

## Module structure and build order

Build strictly in this order -- each layer depends on the one before it.

```
clusterpilot/
  ssh/
    session.py      # ControlMaster: connect, run_command, is_connected, disconnect
  cluster/
    probe.py        # sinfo, module avail, sacctmgr -- parse and cache in SQLite
                    # sinfo must capture: partition name, max walltime, GPU gres,
                    # node count, state -- enough to populate the partition picker
    cache.py        # SQLite cache layer for cluster state (TTL: 24h)
    profiles.py     # Cluster type definitions: drac, grex. Add new types here only.
  jobs/
    generate.py     # Anthropic API call: cluster context + user description -> script
    submit.py       # rsync upload + sbatch, capture job ID
    state.py        # State machine: PENDING -> RUNNING -> COMPLETED/FAILED
    db.py           # SQLite job log: insert, update, query
  notify/
    push.py         # HTTP POST to ntfy endpoint (or any webhook)
    desktop.py      # libnotify via subprocess (Linux: notify-send)
  daemon/
    poll.py         # Main poll loop: squeue -> state transitions -> notify -> rsync
    service.py      # systemd unit file writer and installer
  tui/
    app.py          # Textual App root
    screens/
      jobs.py       # Job list + detail + log + action buttons (F1)
      submit.py     # Job description input + partition picker + AI script generation + file list (F2)
      config.py     # Cluster profiles + SSH + notify + API key settings (F9)
    widgets/
      job_table.py  # Scrollable job list with status indicators
      log_panel.py  # RichLog widget, auto-scroll
      progress.py   # Walltime progress bar
  config.py         # Config loader: ~/.config/clusterpilot/config.toml
  cli.py            # Entry point: `clusterpilot` command
```

---

## SLURM script generation -- prompt structure

When calling the Anthropic API to generate a SLURM script, the system
prompt must include three layers of context:

1. **Universal SLURM rules** -- valid for all clusters
2. **Cluster-type quirks** -- injected based on `cluster_type` field from
   `cluster/profiles.py` (the DRAC and Grex sections above are the source
   of truth for these quirks)
3. **Probed cluster state** -- actual output of `sinfo`, `module avail`,
   and (for DRAC) `sacctmgr`, cached in SQLite for 24h

The user message is their plain-language job description, plus the
**user-selected partition** which is passed as a hard constraint, not a
suggestion. The AI must honour it and use the correct `--gres` syntax for
that partition's hardware.

Model: `claude-sonnet-4-6`. Opus is not needed for script generation.

---

## Partition picker design

Partition selection is a **required manual step** on the F2 Submit screen,
for all cluster types. The app never auto-selects a partition.

Rationale: partition access is personal -- research groups have dedicated
GPU partitions that general users cannot use, and users generally know which
partitions they are allowed on. Auto-selection would be wrong as often as it
would be right.

**UX flow on F2 Submit:**
1. User selects cluster (dropdown, populated from config)
2. User selects partition (dropdown, populated from the sinfo cache for that
   cluster -- shows partition name, max walltime, GPU availability, node count)
3. User types plain-language job description
4. AI generates script with the chosen partition as a hard `--partition=` value

**What the partition picker shows** (parsed from `sinfo -o "%P %l %G %D %a"`):
- Partition name
- Max walltime (e.g. `24:00:00`)
- GPU resources if any (e.g. `gpu:a100:4`, or `(null)` for CPU-only)
- Number of nodes
- State (up / down / drain)

Show only `up` partitions. Sort GPU partitions to the top since most
ClusterPilot users are running GPU workloads.

**Do not validate** whether the user has access to a given partition -- the
app has no way to know which contributed or restricted partitions a specific
user belongs to. Users know their own access. If they pick a partition they
cannot use, sbatch will reject it with a clear error message that ClusterPilot
surfaces in the log panel.

---

## SSH strategy

System ssh binary via subprocess, not Paramiko. ControlMaster socket
management is more reliable through the system binary and respects the
user's existing `~/.ssh/config`.

`clusterpilot setup` writes entries like the following on first run:

```
Host cedar
    HostName cedar.computecanada.ca
    ControlMaster auto
    ControlPath ~/.ssh/cm_%h_%p_%r
    ControlPersist 4h
    ServerAliveInterval 60

Host narval
    HostName narval.computecanada.ca
    ControlMaster auto
    ControlPath ~/.ssh/cm_%h_%p_%r
    ControlPersist 4h
    ServerAliveInterval 60

Host grex
    HostName grex.hpc.umanitoba.ca
    ControlMaster auto
    ControlPath ~/.ssh/cm_%h_%p_%r
    ControlPersist 4h
    ServerAliveInterval 60
```

`session.run_command(host, cmd)` opens a connection over the existing socket
(sub-second), runs the command, and closes. Each poll cycle is:
connect -> `squeue -j JOB_ID -h` -> disconnect. No persistent pipe.

---

## Notification design

`notify.push` sends a single HTTP POST:

```python
httpx.post(
    config.notifications.endpoint,
    content=message,
    headers={"Title": title, "Priority": priority, "Tags": tags},
)
```

The endpoint string is the user's only configuration. Supported out of the box:
- ntfy.sh free hosted tier (default -- no account needed, sufficient for
  typical ClusterPilot usage volumes)
- Self-hosted ntfy server (single Go binary)
- Any webhook accepting a plain POST body

Users never need a paid ntfy.sh subscription for normal usage.

---

## Monetisation model (open core / hosted SaaS)

ClusterPilot is MIT licensed. The full source is free to use and self-host.

### Free (self-hosted) tier -- always fully functional
- BYOK: user sets `ANTHROPIC_API_KEY` in environment
- BYOE: user configures their own ntfy endpoint
- All features work -- nothing is paywalled in the open source version
- All supported clusters work: DRAC (cedar, narval, graham, beluga) and Grex

### Hosted tier (future, ~$5/month)
If launched, paying users get a pooled API key, managed notification
endpoint, cloud job history, and a web dashboard.

Framing: "ClusterPilot is 100% free and open source. A hosted tier exists
for researchers who want zero setup -- subscribing also supports development."

**Do not build the hosted tier yet.** Ship a working open source v0.1 on
cedar + grex first. Early adopters are already waiting.

---

## Code conventions

- British English in all comments, docstrings, and user-facing strings
- Type hints on all function signatures
- Dataclasses or TypedDicts for structured data, not bare dicts
- No class where a module-level function suffices
- Each module has one clear responsibility (see structure above)
- All subprocess calls go through `ssh/session.py` -- never call ssh directly
  from other modules
- All cluster-specific logic lives in `cluster/profiles.py` -- adding a new
  cluster type means editing exactly one file
- Errors surface as typed exceptions, not bare strings
- Tests live in `tests/` mirroring the source structure
- Use `pytest` and mock subprocess calls -- never make real SSH calls in tests

---

## TUI aesthetic reference

Phosphor amber terminal aesthetic. Warm amber (`#e8a020`) on near-black
(`#0c0a06`). Status colours: green (RUNNING), amber (PENDING), cyan
(COMPLETED), red (FAILED). Box-drawing borders. Monospace throughout.
Keyboard-driven with persistent footer showing shortcuts.
See `clusterpilot-tui.jsx` in the project root for the full visual mockup.

Textual widget mapping:
- Partition picker -> `Select` widget, populated from SQLite sinfo cache
- Job list -> `ListView` with custom `ListItem` subclass
- Log output -> `RichLog` with auto_scroll=True
- Progress bars -> `ProgressBar` widget
- Layout -> `TabbedContent` for F1/F2/F9 tabs, `Horizontal`/`Vertical` containers
- Footer shortcuts -> `Footer` widget with key bindings

---

## Distribution

```
pip install clusterpilot
```

Entry point: `clusterpilot` (defined in `pyproject.toml`).
First run: `clusterpilot setup` -- interactive wizard that writes config
and installs the systemd user service.

Target: PyPI, MIT licence, public GitHub repo.
Future: conda-forge (many HPC users prefer conda).

Priority for v0.1: cedar + grex working end-to-end. Expand to graham
and beluga after initial user feedback.