# Contributing to ClusterPilot

Thanks for your interest in contributing. ClusterPilot is a small open-source project
built by a computational physics PhD student, and contributions of all sizes are welcome.

---

## Before you start

- Check the [open issues](https://github.com/ju-pixel/clusterpilot/issues) to see if your
  idea or bug is already being tracked.
- For anything larger than a one-line fix, open an issue first to discuss the approach.
  This saves you from writing code that duplicates work in progress or conflicts with
  planned direction.

---

## Development setup

```bash
git clone https://github.com/ju-pixel/clusterpilot
cd clusterpilot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Verify everything works:

```bash
pytest          # 128 tests, no SSH or cluster access required
ruff check .    # linter
```

All tests mock out SSH subprocess calls — you do not need a cluster account to contribute.

---

## Project structure

The module build order matters: each layer depends on the one below it.

```
clusterpilot/
  ssh/           ControlMaster subprocess wrappers — all SSH goes through here
  cluster/       sinfo/module probe + SQLite cache
  jobs/          AI script generation, sbatch submit, state machine
  notify/        ntfy.sh HTTP push
  daemon/        async poll loop + systemd service installer
  tui/           Textual app (F1 jobs / F2 submit / F9 settings)
  config.py      config loader
  db.py          aiosqlite job history
```

Key rules (enforced in code review):

- All SSH/subprocess calls go through `ssh/session.py`. Never call `ssh` directly from
  other modules.
- All cluster-specific SLURM quirks live in `cluster/profiles.py`. Adding a new cluster
  type means editing exactly one file.
- British English in all comments, docstrings, and user-facing strings.
- Type hints on all function signatures.
- Dataclasses or TypedDicts for structured data — no bare dicts across module boundaries.

---

## Making a change

1. Fork the repo and create a branch from `main`.
2. Write your change. Add or update tests in `tests/` to cover it.
3. Run `pytest` and `ruff check .` — both must pass cleanly.
4. Open a pull request against `main`.

PR titles should be short and imperative: *Add Beluga cluster profile*, *Fix sinfo
parse for drained partitions*, *Handle missing API key gracefully on F2*.

---

## Good first issues

Issues labelled [`good first issue`](https://github.com/ju-pixel/clusterpilot/issues?q=label%3A%22good+first+issue%22)
are self-contained and well-scoped. They are a good place to start if you are new to the
codebase.

---

## Reporting bugs

Use the [bug report template](https://github.com/ju-pixel/clusterpilot/issues/new?template=bug_report.yml).
The most useful thing you can include is a minimal reproduction: which cluster, what you
typed, and the exact error or unexpected behaviour. Log output from the F1 screen or the
daemon is also very helpful.

---

## Licence

By contributing, you agree that your changes will be released under the [MIT licence](LICENSE).
