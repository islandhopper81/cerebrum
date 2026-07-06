"""Thin, language-agnostic git wrappers for the single-mutant lifecycle.

The engine touches git directly here — create an isolated worktree off ``HEAD``,
check/apply a patch — while everything target-specific (install, test) stays in
:mod:`cerebrum.exec.command`. Unlike ``run_command`` these use ``git`` in
list-argument form (no shell) and feed patches on stdin, so paths and diff bodies
need no quoting.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


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
