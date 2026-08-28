# Changelog

All notable changes to ClusterPilot, newest first. Issue numbers refer to
github.com/ju-pixel/clusterpilot.

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
