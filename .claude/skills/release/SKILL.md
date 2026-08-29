---
name: release
description: Publish a ClusterPilot release end to end: preflight checks, version bump, changelog, build, secret-scan of the artefacts, PyPI upload, git tag and GitHub release, post-release verification from the live index. Trigger on "release", "publish to PyPI", "bump the version", "ship vX.Y.Z", or any request to get local changes onto PyPI.
---

# ClusterPilot Release

## Why this skill exists

The 0.3.0 release shipped the proxy secrets inside the sdist and had to be
yanked from PyPI, with token rotation to follow. The same day, `twine
upload dist/*` failed because nothing had been built, and the GitHub
release step was nearly forgotten. Releasing by memory is how that happens.
This skill is the checklist, executed in order, aborting loudly instead of
improvising. Do not skip steps because the release "is small".

## Credential rules (read before anything else)

- Tokens come from the OS keyring or an environment variable, never from
  the conversation. This repo now releases from two machines, so resolve
  the token per platform and never echo either value:
  - macOS (MacBook): `keyring get https://upload.pypi.org/legacy/ __token__`.
  - Linux (workstation): `keyring` needs a running Secret Service (GNOME
    Keyring or KWallet) and raises `NoKeyringError` in a plain SSH session
    with no session bus, which is how the workstation is usually reached.
    Prefer `TWINE_PASSWORD` there, exported from the shell profile or piped
    from `pass`.
  - Either machine: confirm with `test -n "$TWINE_PASSWORD"` before trying
    the keyring, since an exported variable wins and costs nothing to check.
  If neither source yields a token, stop and ask Julia to set one up. Never
  write a token into a file inside the repo.
- If Julia pastes a token, API key, or secrets blob into chat, stop and say
  so: that credential is now in a transcript and must be treated as
  compromised. Point her at the rotation steps below, then continue the
  release with the rotated credential. Do not use the pasted value.
- Never run `fly secrets set` or similar with inline secret values in a
  logged command. Have Julia run those herself in a plain terminal.

## Step 1: preflight (abort on any failure)

1. `git status --porcelain` is empty and the branch is `main`. Uncommitted
   work does not go into a release by accident.
2. Full test suite passes: `python -m pytest tests/`. A release with a red
   suite does not exist.
3. Version consistency: the version in `pyproject.toml` matches
   `clusterpilot/__init__.py`. If they disagree, fix before bumping.
4. `git log <last-tag>..HEAD --oneline` shows what is actually being
   released. Show Julia this list; it is the release's contents.

## Step 2: version bump

Semver against the commit list: bug fixes only → patch; new user-facing
behaviour → minor; breaking config or CLI changes → major (and a
conversation first). State the chosen version and why in one line; ask only
if the commit list genuinely straddles the line. Update `pyproject.toml`
and `clusterpilot/__init__.py` together.

## Step 3: changelog

Add a `## vX.Y.Z (YYYY-MM-DD)` section to `CHANGELOG.md` (create the file
if missing) from the commit list: one line per user-visible change, plain
language, British English, no em-dashes. Fixed issues get their `#N`
reference. The changelog is public marketing ("actively maintained" is
visible nowhere else), so write it for a user, not for git.

## Step 4: build

```
rm -rf dist/ build/
python -m build
```

Both artefacts (sdist `.tar.gz` and wheel `.whl`) must exist in `dist/`
before anything is uploaded. `twine upload dist/*` against an empty or
stale `dist/` is a known failure mode here.

## Step 5: secret-scan the artefacts (the 0.3.0 rule, never skip)

Inspect what is actually inside both artefacts:

```
tar -tzf dist/*.tar.gz
unzip -l dist/*.whl
```

The ONLY top-level content shipped is the `clusterpilot/` package plus
standard packaging metadata (and README/LICENSE). Abort immediately if the
listing contains any of: `proxy/`, `api/`, `dashboard/`, `frontend/`,
`site/`, `tests/`, `tasks/`, `.env`, anything named `*secret*`, `*token*`,
`*.pem`, or a `.jsx` mockup. Then grep the sdist contents for key-shaped
strings (`sk-ant`, `pypi-`, `AKIA`) before upload. If the scan fails, fix
`pyproject.toml` packaging config (or `MANIFEST.in`), rebuild, rescan.

## Step 6: upload

`twine upload dist/*` using keyring or `TWINE_PASSWORD` (Step 0 rules).
If authentication fails, the answer is rotate-and-retry via
pypi.org/manage/account/token, never "paste the token here".

## Step 7: tag and GitHub release

```
git tag vX.Y.Z
git push && git push --tags
gh release create vX.Y.Z --title "vX.Y.Z" --notes-file <(changelog section)
```

The GitHub release is not optional; it is what watchers and the awesome
lists see. Use the changelog section verbatim as the notes.

## Step 8: verify from the live index

In a throwaway venv (use the scratchpad dir, not the repo):

```
python -m venv /tmp-venv && pip install clusterpilot==X.Y.Z
clusterpilot --version && python -c "import clusterpilot"
```

PyPI can take a minute to serve a new version; retry briefly before
declaring failure. A release is done when this passes, not when twine
exits 0.

## Step 9: aftercare

- conda-forge: the regro-cf-autotick-bot usually opens a version-bump PR on
  the feedstock within hours; check for it next session and merge. If it
  has not appeared in a day, bump `recipe/meta.yaml` manually.
- Local machines: `pip install -U clusterpilot` on the workstation picks up
  the release. For testing unreleased changes locally, use
  `pip install -e .` in the repo instead of cutting a release.
- Featurebase changelog (clusterpilot.featurebase.app/changelog, linked from
  the website's Support page and carrying an RSS feed): post the release as
  an update, rewritten for a researcher rather than copied from git. Title
  `vX.Y.Z: <three or four words on what it buys the user>`, category New (or
  Fixed for a patch), body of three to five bold lead-in paragraphs ending
  with the GitHub release link, a TUI screenshot from `tests/screenshots.py`
  as the featured image, email notification OFF, and the date set to the
  release date (Featurebase stamps the UTC day, which is often tomorrow; the
  picker refuses the "today" cell until another day has been clicked first).
  Drafts go in `tasks/featurebase-changelog-drafts.md` for review before
  posting. Posting needs Julia signed in to Featurebase in a Chrome the
  session can drive; the MacBook's is the practical one.
- Report back: version, PyPI URL, GitHub release URL, plus one plain
  sentence per notable change that Julia can paste into the newsletter or a
  changelog post (the release doubles as content).

## Hard rules

- Never yank or delete a published release without Julia's explicit
  instruction; propose it with reasons.
- Never release from a branch other than main, or with failing tests, or
  with a failed secret-scan. There is no "just this once".
- British English everywhere, including the changelog. No em-dashes.
