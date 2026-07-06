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
- Packaging: `pyproject.toml`, console entry point `cerebrum`

*(The engine is the code in this repo. It is deliberately language-agnostic about
the codebases it mutates — those are described per-repo in a `cerebrum.yaml`
adapter file, not here.)*

## Repo structure (emerging — see issue #1)

```
src/cerebrum/          # the engine (Python)
  config/              # cerebrum.yaml model + loader (issue #1)
  cli.py               # `cerebrum` entry point
examples/              # sample cerebrum.yaml files (e.g. FeedTheFamily)
tests/                 # pytest suite, mirrors src/cerebrum/
```

## Commands

Run from the repo root, inside the project's virtualenv:

- Install (dev): `pip install -e ".[dev]"`
- Test: `pytest`
- Test with coverage: `pytest --cov=cerebrum`
- Lint: `ruff check .`
- Format: `ruff format .`
- Type-check: `mypy src`

*(These reflect the intended toolchain; `pyproject.toml` lands with issue #1.)*

## Worktree setup

This is a Python project. A worktree created by `/branch` shares the main
checkout's virtualenv (`.venv`) rather than creating its own — do not run a
package install in the worktree. Because the package is an editable install,
`import cerebrum` resolves to the **main checkout**; when running venv-backed
tools against worktree code, set `PYTHONPATH` to the worktree root. `pytest` is
the exception — it prepends the worktree root itself.

## Definition of done (per ticket)

- Acceptance criteria in the issue are met and covered by tests.
- `pytest`, `ruff check`, and `mypy src` pass.
- PR opened against `develop` with `Closes #<N>`.
