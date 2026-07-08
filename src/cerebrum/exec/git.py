"""Thin, language-agnostic git wrappers for the single-mutant lifecycle.

The engine touches git directly here — create an isolated worktree off ``HEAD``,
check/apply a patch — while everything target-specific (install, test) stays in
:mod:`cerebrum.exec.command`. Unlike ``run_command`` these use ``git`` in
list-argument form (no shell) and feed patches on stdin, so paths and diff bodies
need no quoting.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class GitError(Exception):
    """Raised when a git invocation the engine depends on fails."""


def _run_git(
    args: list[str], cwd: Path, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=input_text,
    )


def require_git_repo(repo_root: Path) -> None:
    """Raise :class:`GitError` if ``repo_root`` is not inside a git work tree."""
    result = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=repo_root)
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise GitError(f"not a git repository: {repo_root}")


def worktree_add(repo_root: Path, worktree_path: Path, ref: str = "HEAD") -> None:
    """Add a detached worktree at ``worktree_path`` checked out at ``ref``.

    Detached so no branch is created — the worktree is a throwaway sandbox for a
    single mutant.
    """
    result = _run_git(
        ["worktree", "add", "--detach", str(worktree_path), ref], cwd=repo_root
    )
    if result.returncode != 0:
        raise GitError(
            f"git worktree add failed for {worktree_path}: {result.stderr.strip()}"
        )


def worktree_remove(repo_root: Path, worktree_path: Path) -> None:
    """Remove the worktree at ``worktree_path`` (best-effort; force-removes)."""
    _run_git(["worktree", "remove", "--force", str(worktree_path)], cwd=repo_root)


def apply_check(worktree_root: Path, diff: str) -> bool:
    """Return whether ``diff`` applies cleanly in ``worktree_root`` (no changes made)."""
    result = _run_git(["apply", "--check"], cwd=worktree_root, input_text=diff)
    return result.returncode == 0


def apply(worktree_root: Path, diff: str) -> None:
    """Apply ``diff`` in ``worktree_root``, raising :class:`GitError` on failure."""
    result = _run_git(["apply"], cwd=worktree_root, input_text=diff)
    if result.returncode != 0:
        raise GitError(f"git apply failed: {result.stderr.strip()}")


def discard_changes(worktree_root: Path) -> None:
    """Restore ``worktree_root`` to its committed ``HEAD`` state so it can be
    reused for another mutant: revert tracked-file edits, then remove any
    untracked file a mutant patch introduced."""
    checkout = _run_git(["checkout", "--", "."], cwd=worktree_root)
    if checkout.returncode != 0:
        raise GitError(f"git checkout failed: {checkout.stderr.strip()}")
    clean = _run_git(["clean", "-fd"], cwd=worktree_root)
    if clean.returncode != 0:
        raise GitError(f"git clean failed: {clean.stderr.strip()}")


def changed_lines(repo_root: Path, diff_range: str) -> dict[Path, set[int]]:
    """Return added/modified new-file line numbers per file for ``diff_range``
    (e.g. ``"main..HEAD"``). Keys are absolute resolved paths. A hunk that only
    deletes lines contributes nothing for that file, since there is no new-file
    line to mutate."""
    result = _run_git(["diff", "--unified=0", diff_range], cwd=repo_root)
    if result.returncode != 0:
        raise GitError(f"git diff failed for range '{diff_range}': {result.stderr.strip()}")

    changed: dict[Path, set[int]] = {}
    current: Path | None = None
    for line in result.stdout.splitlines():
        if line.startswith("+++ "):
            current = _resolve_diff_path(line[4:], repo_root)
            continue
        match = _HUNK_HEADER.match(line)
        if match is None or current is None:
            continue
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        if count == 0:
            continue  # pure deletion hunk — no new-file lines added
        changed.setdefault(current, set()).update(range(start, start + count))
    return changed


def _resolve_diff_path(raw: str, repo_root: Path) -> Path:
    if raw == "/dev/null":
        return repo_root  # deleted file; no hunks will be attributed to it
    prefix, _, rel = raw.partition("/")
    return (repo_root / rel).resolve()


def current_commit(repo_root: Path) -> str | None:
    """Return the current ``HEAD`` commit hash, or ``None`` (never raises) —
    informational metadata for correlating a run's score to a code change, not
    load-bearing for the mutation loop itself."""
    result = _run_git(["rev-parse", "HEAD"], cwd=repo_root)
    if result.returncode != 0:
        return None
    return result.stdout.strip()
