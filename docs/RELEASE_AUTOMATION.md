# Release Automation

This repository supports automated stable releases from `main`.

## Workflow

- Changelog builder: `scripts/changelog_builder.py`
- Changelog updater: `scripts/update_changelog.py`
- Criteria evaluator: `scripts/release_criteria.py`
- Changelog workflow: `.github/workflows/changelog-on-main.yml`
- Release workflow: `.github/workflows/release-on-main.yml`
- Publish workflow: `.github/workflows/publish.yml` (tag-driven)
- Release script: `scripts/release.py`

Flow:

1. A push lands on `main`.
2. `changelog-on-main.yml` refreshes generated documentation and, when files changed, commits and pushes them with `[skip release]`.
   - Runs `python scripts/update_changelog.py` to rewrite the `## Unreleased` section in `CHANGELOG.md`, then `git add` / `git commit` / `git push` on the already-updated file (it does **not** re-run `--commit`, because the updater leaves `CHANGELOG.md` dirty).
   - Runs `python scripts/generate_tool_reference.py` to regenerate `docs/TOOLS.md` from the published tool schemas, then commits `chore(docs): refresh generated tool reference [skip release]` when it changed.
   - The suite's `tests/test_tool_reference_sync.py` fails when the committed `docs/TOOLS.md` is stale, and the release quality gates run that suite.
3. `release-on-main.yml` evaluates commits since the latest tag.
4. If eligible, it runs `scripts/release.py --bump <major|minor|patch>`.
5. The script bumps `pyproject.toml`, promotes `## Unreleased` into a versioned entry (or falls back to git commits since the tag), commits, tags (`vX.Y.Z`), and pushes.
6. The tag triggers `publish.yml`, which runs full gates and publishes release artifacts.

## Quick Setup Checklist

Do this once per repository:

1. Create a classic GitHub PAT with `repo` scope.
2. Add repo secret `RELEASE_AUTOMATION_PAT`.
3. Keep this PAT available to `changelog-on-main.yml` and `release-on-main.yml` (least privilege where possible).
4. Verify changelog automation:
   - Push a conventional commit (for example `fix: ...`) to `main`.
   - Confirm `Update Changelog On Main` commits an updated `## Unreleased` section when needed.
5. Verify release automation:
   - Trigger `workflow_dispatch` on `Automated Release On Main` with `patch`, `minor`, or `major`, or
   - Push another releasable conventional commit and wait for the release job.

If both workflows run successfully, setup is complete.

## Local Changelog Preview

Refresh the unreleased section without releasing:

```bash
python scripts/update_changelog.py --dry-run
python scripts/update_changelog.py
```

Refresh the generated tool reference (`docs/TOOLS.md`):

```bash
python scripts/generate_tool_reference.py
python scripts/generate_tool_reference.py --check
```

`--check` exits non-zero when the committed file is stale — the same
condition `tests/test_tool_reference_sync.py` asserts inside the suite.

Commit locally when ready:

```bash
python scripts/update_changelog.py --commit
python scripts/update_changelog.py --commit --push
```

`--commit` allows a dirty tree when **only** `CHANGELOG.md` changed (for example after running the updater once, then committing in a second command). Other uncommitted files still block `--commit`.

## Changelog Entry Limit

`scripts/changelog_builder.py` keeps at most **200** bullets per release section
(`DEFAULT_SUBJECT_LIMIT`). Both entry points expose the same knob:

```bash
python scripts/update_changelog.py --limit 400
python scripts/release.py --bump minor --limit 400
```

200 is a runaway guard, not a routine filter: the largest tag-to-tag range in
this repository's history is 24 commits (`v0.19.0`..`v0.20.0`), and 200
bullets is only a few kilobytes of Markdown. The previous default of 20 sat
below real range sizes and silently dropped the oldest entries of any busy
release.

### What is dropped first

When a range exceeds the limit, entries are ranked before the cut. The surviving
order is newest-first, as before, but the selection is not:

- **Kept first** — `feat:`, `fix:`, `perf:`, `security:`, `revert:`, breaking
  subjects (`type(scope)!:`), unclassifiable subjects, and any dependency-scope
  change such as `chore(deps):` or `build(deps-dev):` (a raised dependency floor
  breaks downstream pins even when the subject reads like maintenance).
- **Dropped first** — `docs:`, `chore:`, `test:`, `ci:`, `style:`, `refactor:`,
  `build:` without a dependency scope.
- **Dropped last** — user-visible entries, oldest first, and only when they
  outnumber the limit on their own.

So a `docs:`/`chore:` wave can never displace a user-visible change. Entry
selection is independent of the semver bump: see [Criteria](#criteria) for what
a breaking subject does to the version.

### How entries are grouped

Bullets are rendered under `### Features`, `### Bug Fixes`, `### Performance`,
`### Security`, `### Dependencies`, `### Refactoring`, `### Documentation`,
`### Internal`, `### Other`, in that order. Dependency-scope changes get their own
`### Dependencies` section rather than `### Internal`, so a raised dependency
floor is visible to the reader it affects.

### The truncation warning

Truncation is never silent. The builder raises
`ChangelogTruncationWarning` (a `UserWarning`), and both scripts print the
report to **stderr** and add a `::warning::` annotation when running under GitHub
Actions. Nothing is written into `CHANGELOG.md`.

```text
[changelog] WARNING: Changelog truncated: kept 8 of 23 releasable commits (limit 8).
[changelog] WARNING: Dropped 15 entries: 15 internal (docs/chore/test/ci/refactor/style/build) and 0 user-visible (feat/fix/perf/security/breaking).
[changelog] WARNING: No user-visible change was lost; only maintainer-facing entries were dropped.
[changelog] WARNING: Re-run with a higher limit (for example --limit 200) to keep every entry.
[changelog] WARNING: Dropped entries:
[changelog] WARNING:   - docs: rebuild the README around the knowledge-layer story 14
...
```

The suggested limit is `max(2 × the current limit, the range size, 200)`, so a
small `--limit` never suggests going *below* the default.

When user-visible changes *are* dropped, the report says so explicitly
(`User-visible changes were dropped (oldest first). Raise the limit before
releasing.`) and lists the lost subjects. Every run also prints a
`[changelog] NOTE:` line naming how many merge, release, `[skip release]`, and
duplicate commits were skipped.

**Before releasing** with a warning in the log, re-run with the suggested
`--limit` value (or edit the `## Unreleased` section by hand) so no change ships
undocumented.

## Criteria

The criteria engine is deterministic:

1. Head commit contains `[skip release]` -> no release.
2. Head commit contains `[release major|minor|patch]` (or `[bump ...]`) -> forced bump.
3. Otherwise, scan commits since latest tag:
- Breaking change (`!` in conventional subject or `BREAKING CHANGE` in body) -> `major`.
- `feat:` -> `minor`.
- `fix:`, `perf:`, `refactor:`, `revert:`, `security:` -> `patch`.
- `docs:`, `chore:`, `ci:`, `test:`, `build:`, `style:` only -> no release.

## Required Repository Secret

Set repository secret:

- `RELEASE_AUTOMATION_PAT`

Use a PAT that can push commits and tags to this repository (`repo` scope for classic PAT).
This is required so tag pushes can trigger downstream workflows reliably.

## Troubleshooting

### Release was skipped with missing PAT warning

Symptoms:

- `release_skipped_missing_pat` job runs.
- `release` job is skipped.

Fix:

1. Add or update `RELEASE_AUTOMATION_PAT` in repo secrets.
2. Re-run the latest `Automated Release On Main` workflow, or push a new commit to `main`.

### Criteria matched but no release happened

Check `decide` job output in `Automated Release On Main`:

- `should_release`
- `bump`
- `reason`
- `has_release_pat`

Expected for an actual release:

- `should_release=true`
- `has_release_pat=true`

### Changelog workflow failed with "Working tree is not clean"

Symptoms:

- `Update Changelog On Main` fails in the **Commit changelog update** step.
- Log shows `Working tree has uncommitted changes outside CHANGELOG.md. Commit or stash them before --commit.`

Cause:

- An older workflow reran `update_changelog.py --commit --push` after step 1 had already written `CHANGELOG.md`.

Fix:

- Ensure `changelog-on-main.yml` commits via `git add` / `git commit` / `git push` after the refresh step, or run a single local `python scripts/update_changelog.py --commit --push` from a clean tree.

### Release docs guard failed in CI

Symptoms:

- `Release Docs Guard` fails with `Release automation files changed without docs updates`.

Fix:

- Update `docs/RELEASE_AUTOMATION.md` or `README.md` in the **same commit** whenever you change release automation scripts or workflows (`release-on-main.yml`, `changelog-on-main.yml`, `update_changelog.py`, etc.).

### Changelog truncated warning in the log

Symptoms:

- `Update Changelog On Main` or the release job logs `[changelog] WARNING: Changelog truncated: kept N of M releasable commits`.
- GitHub annotates the run with `Changelog truncated to N/M commits`.

Cause:

- The range exceeded `DEFAULT_SUBJECT_LIMIT` (200), or a lower `--limit` was passed.

Fix:

1. Read the `Dropped entries:` list in the log.
2. Re-run with the suggested limit, for example `python scripts/update_changelog.py --limit 400` (or `python scripts/release.py --bump minor --limit 400`).
3. If the warning says user-visible changes were dropped, do not release until they appear in `## Unreleased` — re-run with the higher limit, or add the missing bullets by hand.

### How to force one release now

Use `workflow_dispatch` on `Automated Release On Main` and select:

- `patch`
- `minor`
- `major`

This bypasses auto detection for that run only.

## Guardrails

- The automation no-ops when no releasable commits exist.
- The release commit/tag itself does not re-trigger a second release, because there are no commits past the new tag.
- Stable release publishing remains gated by `publish.yml` quality + novelty checks.
- The MCP wire contract is gated separately, by `scripts/smoke_mcp_stdio.py` in
  the `Tests` workflow (3.13/ubuntu): it asserts the negotiated protocol
  version, that every tool publishes both `outputSchema` arms, the tool
  name/count set, and that an unknown argument is rejected with `isError: true`.
  `publish.yml` does **not** re-run it, so a release can only ship what already
  passed `Tests` on the commit it tags.
- `ruff` is pinned to `>=0.7.0,<0.17` with an explicit rule set in
  `pyproject.toml`; both workflows lint `src/` and `tests/`. `scripts/` is
  linted locally and by `scripts/pre_push_check.py`, so the release tooling
  ships clean without being a CI gate.

## Manual Override

`release-on-main.yml` also supports `workflow_dispatch` with optional forced bump:

- `patch`
- `minor`
- `major`

## Operational Notes

- Commit directive `[skip release]` on the head commit suppresses release.
- Commit directive `[release major|minor|patch]` (or `[bump ...]`) on the head commit forces a bump.
- Release commit/tag pushes trigger downstream workflows:
  - `Tests` on `main`
  - `Publish to PyPI` on tag `v*`
