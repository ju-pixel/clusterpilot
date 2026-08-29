# Changelog

All notable changes to ClusterPilot, newest first. Issue numbers refer to
github.com/ju-pixel/clusterpilot.

## v0.7.0 (2026-08-29)

### Added

- ClusterPilot now records what the scheduler actually reserved for each
  finished job: the CPU, GPU and node allocation, the reserved core-hours and
  GPU-hours summed across every task of an array, the true runtime and the
  exit code. It comes from one `sacct` call at the moment a job finishes, so
  it costs nothing while the job is running. Hosted subscribers get all of it
  on the dashboard, which until now knew less about a job than the terminal
  did.
- `clusterpilot backfill` recovers those figures for jobs that finished under
  an earlier release. Accounting is written when a job ends and there is no
  second chance later, so older jobs have none. `sacct` still remembers for as
  long as your site keeps its accounting records, which makes this worth
  running once, soon. `--dry-run` reports what it would recover without
  changing any job; `--cluster` and `--limit` narrow it down. Jobs past your
  cluster's retention are reported as such rather than treated as an error.
- `clusterpilot --version` prints the installed version, which it should have
  done from the start and is what a bug report wants first.

### Changed

- The daemon now sends notifications to the ntfy topic set on the dashboard,
  preferring it over the one in `config.toml` when both exist, so changing the
  topic on the web no longer leaves the daemon posting to the old one (#43).
- Hosted tier: annual billing is available at $60 a year alongside $6 a month,
  and group seat bundles can be bought yearly too, at $51 a seat. Both keep
  the founding price for as long as the subscription lasts.

## v0.6.0 (2026-08-28)

### Added

- Trillium (SciNet) as a fourth cluster type. It shares the Alliance
  scheduling and scratch rules and adds its own: quarter-node GPU requests
  with `--gpus-per-node`, no `--mem`, a 24 hour cap, and every write under
  scratch because home is read-only on compute nodes. A hostname containing
  `trillium` is recognised automatically (#29).
- The default model is now `claude-sonnet-5`, a generation newer and a third
  cheaper than Sonnet 4.6. A HARDER JOB switch on the submit screen generates
  one script with `claude-opus-5`. The 4.6 names keep working.
- Hosted tier: the script streams into the pane again instead of appearing
  all at once (#41), and the config screen shows the month's generation
  allowance. Hosted generations are metered at 150 a month, 15 of them on
  Opus 5, with Sonnet 5 as the fallback; the TUI says when a fallback
  happened.
- Generated scripts now see cores and memory per partition and the
  account's walltime ceiling, and the validator refuses requests above
  them (#22, #23). Every GPU job samples `nvidia-smi` into `gpu_usage.csv`
  so the next request can be sized (#31).
- Finished jobs show a `seff` efficiency summary on the jobs screen and in
  notifications (#31).
- `CLUSTERPILOT_HOME` relocates the config, job database, probe cache and
  systemd unit together, and `daemon install` will not overwrite a unit
  that points at a different Python unless forced (#24).
- Julia drivers' `include()` files are found and uploaded with the driver
  (#7). Array jobs get their per-task logs, so failure notifications carry
  an excerpt (#2).

### Changed

- Credential precedence for generation is now the config file key, then the
  hosted token, then the environment variable, so an exported
  `ANTHROPIC_API_KEY` no longer silently bypasses a paid subscription; F9
  shows which one is in use (#25).
- Results are synced under PROJECT DIR (or `~/clusterpilot_jobs`) rather than
  wherever the TUI was launched, and the jobs screen shows where (#15, #16).
- `cluster_type` is validated at config load; an absent key is inferred from
  the hostname with a warning instead of silently becoming generic (#21).

### Fixed

- Generated scripts never wrap the driver in `stdbuf`, which broke CUDA on
  Alliance clusters (#12), and DRAC scripts no longer run `Pkg.instantiate()`
  on internet-less compute nodes (#10).
- Uploads with many extra files no longer trip the SSH timeout (#13); job
  names no longer stack a timestamp on every retry (#14); absolute or `./`
  driver paths are normalised and a driver outside the project is refused
  (#6); an `ntfy_server` that already ends in the topic is corrected (#26);
  a truncated generation now tells you to move parameters into a table
  (#20).
- Hosted tier: trialing subscribers can use the managed key (#4), and the
  dashboard's notification switches are honoured by the daemon (#5).

## v0.5.0 (2026-08-28)

### Added

- A GPU SIZE picker on the submit screen, filled from what the cluster
  reports: whole cards first, then MIG slices such as `a100_3g.20gb`. The
  choice becomes a hard constraint in the generated script and the validator
  checks it before submit. Jobs that use a fraction of a GPU can ask for a
  slice and queue in minutes rather than hours (#30).
- Single-letter keys on the jobs screen: `r` rsync, `k` kill, `t` tail,
  `l` log, `c` clean remote, `d` forget. The labels always said so; now it
  is true (#37).
- Confirmation dialogues for KILL, CLEAN REMOTE, FORGET and for quitting
  while a job is running, each naming exactly what will be removed and
  where (#38).
- A hint line above the status bar that explains whatever has focus, and a
  per-screen key legend in the status bar (#34).
- After a submit, the jobs screen opens on the new job with its details
  filled in; the submit form keeps its fields and clears only the old
  script, so a rerun is one edit away.

### Changed

- CLEAN and DELETE are now CLEAN REMOTE (removes the job's working
  directory on the cluster) and FORGET (drops the local record); the old
  names were easy to confuse (#34).
- The jobs queue shows the full SLURM job id.
- README screenshots are regenerated from a seeded example database.

### Fixed

- Every screen is usable at 100 columns by 30 rows with the keyboard alone:
  the config view scrolls and keeps EDIT CONFIG on screen (#32), the job
  description box is eight rows tall with a scrollbar (#33), the PARAM
  TABLE field no longer vanishes in short terminals (#36), and the action
  buttons on both screens fit on two rows instead of clipping (#39, #40).
- Leaving the partition picker blank no longer emits
  `--partition=Select.NULL`; on Textual 8 the blank sentinel is
  `Select.NULL`, and every picker check now uses it (#11, #42).
- A relative parameter-table path no longer crashes generation (#35).
- Generated DRAC scripts request one GPU of the partition's type rather
  than the node's full inventory (#8), and fall back to a type-less request
  instead of a Narval-only A100 on the H100 clusters (#28).

## v0.4.0 (2026-08-28)

### Added

- Parameter tables for job arrays. Point the submit screen at a CSV or TSV
  file and each array task reads its own row; the array size comes from the
  row count, so nothing is typed twice (#18).
- Generated scripts are validated before they can be submitted: shell
  syntax, the array directive against the parameter table, per-task GPU
  counts against the partition, the walltime against the partition's limit,
  and that the driver the script runs is in the upload set (#19).
- Optional logging of completed runs into a local Fieldnotes store, switched
  on with `[fieldnotes] enabled = true` and off by default.
- The jobs pane shows a per-task breakdown for arrays, such as `5R/27PD`,
  and job notifications carry the same summary.

### Fixed

- Job arrays whose tasks are in more than one state no longer show an
  unknown status, and are no longer reported as finished while tasks are
  still queued. Every line of squeue and sacct output is now aggregated into
  one state, and a mixed-outcome array downloads the results of its
  completed tasks before the failure is reported (#1, #27, #9).
- The "started" notification fires once per job, not once per wave of an
  array.
- Jobs ended by OUT_OF_MEMORY or NODE_FAIL now read as finished in the jobs
  pane, with KILL disabled and CLEAN and RSYNC available (#3).
- Hosted dashboard: job state is reconciled on every poll, so a job no
  longer sticks at PENDING when a transition was missed.
- The source distribution no longer ships the test suite.

## v0.3.1

Previous release; see the GitHub release notes.
