# Changelog

All notable changes to ClusterPilot, newest first. Issue numbers refer to
github.com/ju-pixel/clusterpilot.

## v0.7.5 (2026-09-01)

The dashboard stops telling you things that stopped being true, and the jobs
screen answers "how many of my tasks are running" without a trip to ssh.

### Fixed

- **A job's partition is read from the scheduler, not guessed.** Submit took
  the partition by scraping the generated script, with the literal string
  `skylake` as its fallback. On DRAC and Trillium the script carries no
  `--partition` directive by design, because the scheduler routes the job from
  `--account`, `--gres`, `--time` and `--mem`, so every routed job claimed to
  be in a partition none of those clusters has. The field now starts blank and
  is filled from `squeue` once the job has actually been placed, which costs
  no extra call and finally makes it say something the script cannot. A job
  that has already finished keeps its old value: `squeue` no longer knows, and
  on DRAC `sacct` cannot be reached from a login node (#47). (#57)
- **An array's task breakdown keeps updating on the dashboard.** It was pushed
  once, at the instant the job went RUNNING, and never again, so an array
  reported `10R/60PD` hours after that had stopped being true and the refresh
  button could not help, because the stale number was in the API rather than
  the page. The terminal was right throughout; only the web was frozen. (#72)
- **A running job's log on the dashboard is refreshed while it runs**, rather
  than staying the excerpt captured when the job started. (#72)

### Added

- **The F1 queue shows each array's progress, and the header totals it.** Rows
  carry the per-task breakdown, and the QUEUE header adds it up across active
  jobs, so four arrays on four clusters can be read at a glance instead of
  opening each one or logging into the clusters to count.

## v0.7.4 (2026-09-01)

The job log is readable again in both of the places you look at it, and the
API spend figure can be trusted.

### Fixed

- **A job's Logs tab on the dashboard scrolls, and holds a real log.** The
  page shell was free to grow past the viewport, so nothing had a definite
  height to shrink against, the tab pane took the height of the whole log, and
  no scrollbar ever appeared. There was little to scroll through in any case:
  only the last fifty lines ever reached the dashboard. The daemon now syncs
  up to five hundred lines, trimmed to a size budget from the front and marked
  where it was cut. (#64)
- **`y` copies the OUTPUT LOG panel on the jobs screen.** The panel scrolls,
  so dragging across it moved the log rather than selecting any of it, whilst
  the job detail pane above it selected normally. The key copies everything
  the panel holds, including the lines scrolled out of view, and travels as
  OSC 52, so it works when the TUI is driven over SSH. (#65)
- **The API spend figure counts every generation, and prices each one at its
  own model.** It summed the jobs table, where a row only exists once a job is
  submitted, so every regenerated, abandoned and refused generation was billed
  by the provider and counted nowhere. It also priced a whole history at
  whichever model your config names, which showed an Opus generation at
  Sonnet's rate. Usage is now recorded as each generation finishes, priced per
  model, and your existing history is carried over on first run. (#66)
- **An unpriced model is shown as unpriced rather than guessed at.** A local
  Ollama generation, which costs nothing, was billed on screen at Claude
  Sonnet 4.6's rate at two of the three places cost appears, and Claude Haiku
  4.5 was priced twenty per cent low. (#67)

## v0.7.3 (2026-08-31)

Parameter-table job arrays now work end to end. A real 70-task array was
blocked by four separate faults on this one path, and each was silent about
what it had done.

### Fixed

- **The file picker now puts a file in the field you are in.** Choosing a
  parameter table with PARAM TABLE focused wrote the path into EXTRA FILES
  instead, because the picker filled the first empty field rather than the
  focused one. With the path never reaching PARAM TABLE, nothing parsed the
  table, nothing derived the array size from it, and no reader was rendered:
  the model was left to invent one from your prose description. In the case
  that prompted this it read the first two columns positionally against a
  table whose first column was `task_id`, so every task would have taken its
  own task id as a physics parameter. (#58)
- **The driver-uploaded check is given the real upload set.** It was handed
  the EXTRA FILES field, which is not the upload set: for a Julia project the
  driver is already in the allowlist. So the check did nothing at all when
  EXTRA FILES was empty, and blocked a perfectly good script when EXTRA FILES
  held anything that was not the driver. That is what stopped the array. (#52)
- **EDIT re-runs the checks.** The edit handler replaced the script and
  refreshed the display but validated nothing, so a block stayed on the SUBMIT
  button after you had fixed the line it complained about, and a clean script
  edited into a broken one was submitted unchecked. Both directions now work,
  and the message that says to fix it with EDIT is finally true. (#53)
- **The parameter-table reader is checked into the emitted script.**
  ClusterPilot renders the row-reading block itself so the mapping from array
  index to parameters has one implementation, but nothing confirmed the block
  had survived generation. A script that paraphrased it, substituted a case
  statement or hardcoded the values passed every other check. On a 70-task
  array that is the most expensive silent failure available. It is now a
  blocking finding, as is a second per-task mapping sitting beside the
  table. (#54)
- **A blank ARRAY field with a table now fills itself in.** The array spec
  derived from the row count was written to a local variable and never back to
  the field the submit path reads, so the job lost its per-task log names and
  its array tracking. (#51)
- **A blank line in the middle of a table no longer shifts every task after
  it.** The parser skipped blank lines when counting rows whilst the emitted
  reader selected by physical line number, so the two disagreed from the first
  blank line onwards and each later task ran on its neighbour's parameters.
  Both now count the same way. Line endings are normalised, a stray carriage
  return no longer travels into the last column's value, and a quoted
  delimiter is refused outright rather than being read one way here and
  another way by `cut` on the cluster. (#55)
- **A fixed export that shadows a table column is now reported.** A job
  description that set `SGL_LATTICE=cubi` alongside a table whose
  `SGL_LATTICE` column said `cubic` produced both, with no complaint and no
  way to tell which had won. The table is the source of truth; the collision
  is a warning that names the column, the line, and which one takes effect.
  (#60)

### Verified

The workflow this release unblocks is covered by a test that drives the real
submit screen: a Julia CUDA project, a 70-row TSV headed `task_id,
SGL_LATTICE, SGL_ETA, SGL_HSTAR, SGL_SEED_BASE, SGL_BOX_PARITY`, one MIG
slice per task on a DRAC cluster, the table chosen into PARAM TABLE and ARRAY
typed as `0-69`. The emitted script carries the rendered reader, every task
exports its five columns from its own row, the logs are named `%x-%A-%a.out`,
and SUBMIT is enabled. The model call is stubbed there, so what is proven is
everything ClusterPilot does around the generation rather than the generation
itself.

## v0.7.2 (2026-08-30)

### Fixed

- **A results download that fails is now retried.** ClusterPilot marks a job
  finished the moment it finishes, which meant it stopped being watched
  straight afterwards, so a single rsync that failed at three in the morning
  left your results sitting on the cluster with nothing but "SYNCED no" on
  the jobs screen to say so. The daemon now tries again, up to five times.
  Jobs that never produced results are not retried, and a cluster that is
  simply unreachable does not use up the attempts.
- **Grex now points at `grex.hpc.umanitoba.ca`, not a single login node.**
  The starter config named `yak`, which is one machine; when it went down
  ClusterPilot could not connect while a plain `ssh grex.hpc.umanitoba.ca`
  still worked, because that name resolves to several nodes and falls through
  to a live one. Existing configs are not changed: edit the `host` line under
  your Grex cluster to pick this up.

### Hosted tier

- The dashboard keeps up now. The job list refreshes itself and says how old
  it is, you can search it and filter by cluster and status, and each job has
  its own page with the full script, log and resource accounting. A failed
  job shows why it failed in the list, so you usually do not need to open it.
  Older jobs load a page at a time instead of stopping at the most recent 200.

## v0.7.1 (2026-08-30)

### Fixed

- **Job accounting now works on Alliance clusters, where 0.7.0 silently did
  nothing.** Reading it needs `sacct`, and `sacct` needs the accounting
  database, which Narval, Fir, Nibi, Rorqual and Trillium login nodes cannot
  reach. ClusterPilot now measures instead: it reads what the scheduler
  allocated from `squeue`, which does answer there, and adds up the running
  task count against it on every poll. For a job array that is more accurate
  than a single start-to-finish figure, which would charge one task's
  allocation for the whole span however many were running.
- Every figure now records where it came from, either your scheduler's
  accounting or ClusterPilot's own measurement, so a measurement is never
  presented as an accounting record.
- **GPU jobs are no longer valued as if they were CPU jobs.** ClusterPilot
  now tracks the scheduler's billing weight, which is what your allocation is
  actually charged. On Narval a job with four CPUs and four A100s bills at
  16000 while a plain eight-CPU job bills at 8, so counting cores alone
  understated a GPU job by three orders of magnitude.
- `clusterpilot backfill` no longer claims your jobs are past the cluster's
  accounting retention when it simply could not reach the accounting
  database. It now says which happened, and prints what the cluster said.

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
