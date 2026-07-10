# CLAUDE.md — Cerebrum

Project conventions for AI agents and contributors. Skills (`/ship`, `/branch`,
`/implement-ticket`, `/close-ticket`, `/pr`, `/refine-ticket`) read this file to
detect the issue tracker, git workflow, and test commands.

## What this project is

Cerebrum is **LLM-based mutation testing, portable to any codebase**. It inserts
small realistic bugs ("mutations") into a target repo one at a time, runs that
repo's test suite, and reports whether the tests caught each mutation. Survivors
reveal test-suite gaps. See [README.md](README.md) for the architecture (engine +
adapter split, mutant lifecycle, run modes).

## Issue tracker

- `issue_tracker: github`
- Repo: `islandhopper81/cerebrum`
- `github_project: 2` (owner `islandhopper81`) — the "Cerebrum" Projects board
  (Todo / In Progress / Done). `/close-ticket` moves an issue's card to **Done**
  here after closing it.
- Work is tracked as GitHub Issues under milestone **M1** (#1–#6). Reference issues
  by bare number (e.g. `1`) or `#1`.
- Not Jira, not Linear — no `jira_project_key` / `linear_team`.

## Git workflow

- **`develop` is the primary/default branch.** Feature branches branch off
  `develop` and merge back into `develop`.
- **Do NOT merge into `main`.** `main` is the stable/release branch, left untouched
  during normal development.
- Base branch for branches and PRs: **`develop`**.
- PRs auto-close their issue via `Closes #<N>` in the PR body.

### Branch naming

`{type}/{issue-number}-{short-slug}`, type inferred from issue labels:
- `bug` label → `fix/`
- `chore` / `infra` label → `chore/`
- otherwise → `feat/`

Example: issue #1 (`adapter` label) → `feat/1-config-adapter`.

## Tech stack (engine)

- **Python 3.11**
- **Pydantic v2** — typed/validated config model
- **PyYAML** (`safe_load`) — parse `cerebrum.yaml`
- **pytest** — tests
- **ruff** (lint/format) + **mypy** (type-check)
- Packaging: `pyproject.toml`, console entry point `cerebrum`, published to PyPI as
  `cerebrum-engine`

*(The engine is the code in this repo. It is deliberately language-agnostic about
the codebases it mutates — those are described per-repo in a `cerebrum.yaml`
adapter file, not here.)*

Every target repo running Cerebrum should add `.cerebrum/` to its own
`.gitignore` — that directory holds engine output (mutant records, run history,
`history.sqlite`), not source, and nothing currently does this for you.

## Repo structure

This repo holds two independently-versioned, independently-published Python packages: the
engine itself (root `pyproject.toml`) and one optional integration client
(`integrations/cerebrum-cloud/`, its own `pyproject.toml`). They do not depend on each other
— the integration never imports `cerebrum`, and the engine has no knowledge of any specific
`after_run` sink. See "Packaging & releases" below for how each ships.

```
pyproject.toml         # root package: dist name cerebrum-engine, console script `cerebrum`
src/cerebrum/           # the engine (Python)
  config/              # cerebrum.yaml model + loader
  exec/                # shared shell command runner + git wrappers
  baseline/            # baseline stage: install/test/require-green/coverage
  generate/            # GENERATE stage: operator seam + LLM operator + severity
  execute/             # EXECUTE stage: lifecycle, targeting, worktree pool + parallel runner
  report/              # REPORT stage: score, survivor report, suggested tests, trend
  cli.py               # `cerebrum` entry point (`validate`, `baseline`, `mutate`, `run`, `report`)
examples/              # sample cerebrum.yaml files (e.g. FeedTheFamily)
tests/                 # pytest suite for the engine, mirrors src/cerebrum/

integrations/cerebrum-cloud/    # standalone package: dist name cerebrum-cloud-push
  pyproject.toml               # separate version, deps ([] — stdlib only), own ruff/mypy config
  src/cerebrum_cloud_push/      # push.py: reads local .cerebrum/ artifacts, POSTs to Cerebrum
                                # Cloud's ingest-run Edge Function; console script `cerebrum-cloud-push`
  tests/                       # pytest suite for this subpackage only

.github/workflows/
  publish.yml               # cerebrum-engine: on GitHub Release published -> build + PyPI publish
  test-cloud-push.yml       # cerebrum-cloud-push: pytest/ruff/mypy on PRs/pushes touching
                             # integrations/cerebrum-cloud/**
  publish-cloud-push.yml    # cerebrum-cloud-push: on cloud-push-v* tag -> test job -> build + PyPI publish
```

## Commands

Run from the repo root, inside the project's virtualenv:

- Install (dev): `pip install -e ".[dev]"`
- Test: `pytest`
- Test with coverage: `pytest --cov=cerebrum`
- Lint: `ruff check .`
- Format: `ruff format .`
- Type-check: `mypy src`

The `integrations/cerebrum-cloud/` subpackage has its own copy of these (own `pyproject.toml`,
own `[tool.ruff]`/`[tool.mypy]` — they don't cascade from the root). Run them from inside
that directory against a separate install (`pip install -e ".[dev]"` there); root `testpaths`/
`mypy_path` scoping keeps the two test suites and type-checks from double-running each other.
There is currently no CI gate on the root engine itself (`src/cerebrum/`) — `pytest`,
`ruff check .`, `mypy src` at the repo root must be run locally before opening a PR. CI does
exist for the `integrations/cerebrum-cloud/` subpackage (`test-cloud-push.yml`).

## Packaging & releases

Both packages publish to PyPI via **Trusted Publishing** (GitHub OIDC, `pypa/gh-action-pypi-publish`)
— no stored API token. Both use a GitHub Actions environment named `pypi` as the trust
boundary; that environment must exist in this repo's Settings before either workflow can
publish, and each PyPI project has a pending/registered trusted publisher pointing at this
repo + the specific workflow filename below.

### `cerebrum-engine` (the engine, root `pyproject.toml`)

1. Bump `version` in root `pyproject.toml`.
2. Merge `develop` → `main` via PR (releases are cut from `main`, never `develop`).
3. On `main`, create a GitHub Release (tag `vX.Y.Z`) and publish it.
4. `.github/workflows/publish.yml` triggers on `release: published`, builds the sdist/wheel,
   and publishes to PyPI.
5. Verify: `pip install cerebrum-engine` in a clean venv, `cerebrum --help`.

### `cerebrum-cloud-push` (`integrations/cerebrum-cloud/`)

Independently versioned from the engine — a Cerebrum Cloud ingest-API change shouldn't force
an engine release, and vice versa.

1. Bump `version` in `integrations/cerebrum-cloud/pyproject.toml`.
2. Merge `develop` → `main` via PR.
3. On `main`, push a tag `cloud-push-vX.Y.Z` (not a GitHub Release — this package triggers on
   the tag push itself). The tag's version suffix must match the `pyproject.toml` version
   exactly; `publish-cloud-push.yml` fails fast if they don't match.
4. `.github/workflows/publish-cloud-push.yml` triggers on `push: tags: cloud-push-v*`, runs
   its own `test` job (pytest/ruff/mypy) first, and only builds + publishes to PyPI if that
   passes (`publish` job has `needs: test`) — a broken tag cannot reach PyPI.
5. Verify: `pip install cerebrum-cloud-push` in a clean venv, `cerebrum-cloud-push --help`.

## Worktree setup

This is a Python project. A worktree created by `/branch` shares the main
checkout's virtualenv (`.venv`) rather than creating its own — do not run a
package install in the worktree. Because the package is an editable install,
`import cerebrum` resolves to the **main checkout**; when running venv-backed
tools against worktree code, set `PYTHONPATH` to the worktree root. `pytest` is
the exception — it prepends the worktree root itself.

This sharing arrangement is specific to the root engine package. For a ticket that touches
`integrations/cerebrum-cloud/`, the shared root `.venv` has no relationship to that
subpackage (it isn't installed into it, editable or otherwise) — install it separately,
e.g. into its own scratch venv (`pip install -e integrations/cerebrum-cloud[dev]`), before
running its tests/lint/type-check.

## Definition of done (per ticket)

- Acceptance criteria in the issue are met and covered by tests.
- `pytest`, `ruff check`, and `mypy src` pass — from the repo root for engine changes, or
  from `integrations/cerebrum-cloud/` for changes scoped to that subpackage.
- PR opened against `develop` with `Closes #<N>`.
