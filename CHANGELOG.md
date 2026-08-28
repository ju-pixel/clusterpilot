# Changelog

All notable changes to ClusterPilot, newest first. Issue numbers refer to
github.com/ju-pixel/clusterpilot.

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
