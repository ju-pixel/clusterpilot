---
title: Getting started
category: Getting started
excerpt: Install ClusterPilot, write a config file for your cluster, and submit your first SLURM job from the terminal UI. Roughly ten minutes of setup.
order: 1
draft: false
---
ClusterPilot turns a plain-language description of a job into a working SLURM script, uploads your project, submits it, and syncs the results back when it finishes. It runs entirely in the terminal. This page takes you from nothing to a queued job.

## Install it

```bash
pip install clusterpilot
# or
conda install -c conda-forge clusterpilot
```

You need Python 3.9 or newer, the system `ssh` binary (standard on macOS and Linux), and an API key for the AI provider you want to use.

## Write the config

Run `clusterpilot init` to create a starter config at `~/.config/clusterpilot/config.toml`, then open it. On a first run without a config, launching the TUI does the same thing: it writes the starter file, prints where it went, and exits.

The file has three parts: your defaults, one block per cluster, and notifications.

```toml
[defaults]
model = "claude-sonnet-5"
api_key = ""              # or set ANTHROPIC_API_KEY in your shell
poll_interval = 300       # seconds between job status checks

[[clusters]]
name = "narval"
host = "narval.alliancecan.ca"
user = "yourusername"
account = "def-yoursupervisor"
scratch = "/scratch/yourusername"
cluster_type = "drac"
```

Add as many `[[clusters]]` blocks as you use. They all appear in the cluster dropdown and are connected to on startup.

### Set cluster_type explicitly

`cluster_type` decides which cluster quirks get injected into the generated script. There are three values:

| Value | Use for |
|-------|---------|
| `drac` | Digital Research Alliance of Canada (Fir, Narval, Nibi, Rorqual, Trillium) |
| `grex` | University of Manitoba Grex |
| `generic` | Any other SLURM cluster |

Leaving it out is not an error and produces no warning: the cluster silently becomes `generic`. On an Alliance cluster that is the wrong answer. You lose the `$SCRATCH` rule, you get a `--partition=` line that `sbatch` rejects, and CUDA jobs lose the preparation step that makes them find the GPU. Set the value on every cluster block, including the ones where `generic` is correct.

Watch out for one trap in the starter file: the template `[[clusters]]` block ships with `cluster_type = "grex"`. If you copy it for an Alliance cluster and forget to change that line, you inherit Grex behaviour rather than the generic default.

The `scratch` setting is where ClusterPilot puts each job's directory on the cluster. On Alliance clusters this must be your scratch space, never your home directory. Run `echo $SCRATCH` after logging in and paste the path it prints.

## Submit a job

Launch the TUI with `clusterpilot` and press **F2**.

1. Pick your cluster from the dropdown.
2. Pick a partition. The list comes from a live `sinfo` cache and shows availability. ClusterPilot never picks for you; this step is deliberately manual.
3. Set **PROJECT DIR** to your project root, the folder that holds your driver script (and `Project.toml`, for a Julia project). Do not point it inside `src/`.
4. Describe the job in ordinary English, for example: *Run train.py on one A100 for four hours, 32 GB of memory, eight CPUs.*
5. Generate. Read the script it produces, edit anything you disagree with, and submit.

Your files are rsynced to a job-specific directory under `scratch`, then `sbatch` runs over the SSH connection that is already open.

## Watch it run

Press **F1** for the job list. It shows status, walltime used, and a live tail of the SLURM log. A background daemon polls `squeue` every `poll_interval` seconds rather than holding a connection open, so nothing breaks if you close your laptop.

When a job finishes, the output files are rsynced back to your local project directory automatically. If you set up an [ntfy.sh](https://ntfy.sh) topic under `[notifications]`, your phone tells you when a job starts, finishes, fails, or is close to its walltime.
