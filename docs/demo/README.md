# Demo clip

`clusterpilot-demo.mp4` and `clusterpilot-demo.gif` are **generated**, not
recorded. Nobody sat in front of a terminal to make them, and nothing in them
comes from a real machine.

Both files are built by `tests/demo_video.py`, which drives the Textual UI
headlessly at 120x36 against a made-up config and a throwaway SQLite database,
saves one SVG per step, renders each to a 2x PNG with the resvg build vendored
under `frontend/node_modules`, inserts phosphor-amber title cards, and hands the
lot to ffmpeg with a per-frame duration list.

| File | Format | Size |
|---|---|---|
| `clusterpilot-demo.mp4` | H.264, yuv420p, 1724x1080, 30 fps, 1 min 35 s | 2.5 MB |
| `clusterpilot-demo.gif` | 960x602, 12 fps, 1 min 35 s | 1.2 MB |

The GIF is the one to put in a README; the MP4 is the one to put on a page.

## The data is invented

The user is `alice`, the account `def-alice`, the clusters `grex`
(`login.example.ca`) and `narval` (`narval.example.ca`), and the jobs are
`ising-sweep`, `zfc-cooling`, `replica-exchange`, `hysteresis-loop` and
`anisotropy-scan`. The API key shown masked on the config screen is the string
`sk-ant-demo-not-a-real-key`. None of it is real, and the script never opens an
SSH connection, calls an AI provider, reads the real config or touches the real
job database.

The invented data is shared with the README screenshots: `tests/demo_video.py`
imports `tests/screenshots.py` and reuses its config, its probe, its job
records, its job description and its SLURM script, so the clip and the stills
can never drift apart.

## What the clip shows

1. Title card.
2. F2 SUBMIT, filled field by field: cluster, partition, the GPU SIZE picker
   open on a whole A100 and its two MIG slices, project directory, driver
   script, extra files, array spec.
3. The job description typed into the box.
4. The script pane filling line by line, the validator blocking a first draft
   that asks for more walltime than the partition allows, then the corrected
   script with SUBMIT enabled.
5. The submit hand-off to F1 on the new job.
6. F1 JOBS: the queue, the array job's `3R/5PD` breakdown, the log pane filling,
   and `t` cycling to the next array task.
7. The CLEAN REMOTE confirmation modal, opened with `c` and cancelled with `n`.
8. F9 CONFIG, scrolled.
9. Closing card.

The findings in step 4 come from `clusterpilot.jobs.validate` run over the
demo script for real. They are not staged text.

## Regenerating

From the repository root, with the project's virtualenv:

```
.venv/bin/python tests/demo_video.py
```

It needs `ffmpeg` on the path and the frontend's `node_modules` present (for
resvg). Nothing is installed and nothing is downloaded. Frames are written to a
scratch directory outside the repository; only the two files here are updated.

Useful flags:

- `--frames-only` stops after the PNG frames and prints the running time, which
  is the quickest way to check a change to the script before paying for the
  encode.
- `--no-gif` builds the MP4 only.
- `CLUSTERPILOT_DEMO_FRAMES=/some/dir` puts the working frames somewhere
  specific. Wherever they go, it is never inside the checkout.

To change the pacing, edit the `hold=` seconds in `record()`; the script prints
the total running time every run.
