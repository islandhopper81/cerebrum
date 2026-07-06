"""Provide an isolated git worktree for a single mutant, then tear it down.

Create a detached worktree off ``HEAD`` in a temp dir, run the module's
``install`` inside it (gitignored build deps — e.g. ``node_modules`` — do not
come across with a worktree, so tests could not otherwise run), yield the
worktree root, and always remove it. #4 replaces this per-call create/remove with
a reused pool; keeping the interface a context manager localises that swap.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from cerebrum.config.model import Module
from cerebrum.exec import git
from cerebrum.exec.command import run_command


class WorktreeError(Exception):
    """Raised when the worktree cannot be prepared — e.g. install failed."""


@contextmanager
def mutation_worktree(repo_root: Path, module: Module) -> Iterator[Path]:
    git.require_git_repo(repo_root)
    parent = Path(tempfile.mkdtemp(prefix="cerebrum-wt-"))
    worktree_root = parent / "tree"
    try:
        git.worktree_add(repo_root, worktree_root, ref="HEAD")
        install_result = run_command(module.install, cwd=worktree_root / module.root)
        if install_result.exit_code != 0:
            raise WorktreeError(
                f"module '{module.name}': install failed in worktree "
                f"(exit {install_result.exit_code}): {module.install}"
            )
        yield worktree_root
    finally:
        git.worktree_remove(repo_root, worktree_root)
        shutil.rmtree(parent, ignore_errors=True)
