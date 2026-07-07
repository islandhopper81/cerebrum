"""A pool of pre-installed git worktrees, reused across many mutants.

Each worktree is created off ``HEAD`` and has the module's ``install`` run
exactly once, at pool creation — the main performance lever versus running
install per mutant. A worker leases a worktree, runs one mutant against it, and
on release the worktree is reverted (:func:`cerebrum.exec.git.discard_changes`)
so the next lease sees the clean baseline state.

Two distinct failures are handled differently:

- **Pool cannot start** (``install`` fails while creating any of the ``size``
  worktrees): abort immediately — a broken install command fails identically for
  every worktree, so partial capacity has no value. Already-created worktrees
  are cleaned up and :class:`WorktreeError` is raised.
- **A worktree breaks after use** (its revert fails): the worktree is dropped
  from circulation rather than reused in a possibly-corrupt state, but this must
  not clobber the mutant result that worktree just produced — the revert
  failure is swallowed here, not propagated to the caller. Once every worktree
  has been dropped this way, a further lease raises :class:`WorktreeError`
  immediately rather than blocking forever on a worktree that will never come
  back.

A :class:`threading.Condition` (not a bare queue) guards availability: a plain
queue's ``get()`` can't be woken by "the pool just became exhausted," so a
waiter could block forever if the *last* live worktree breaks while it's
waiting. The condition is notified on every state change — a release *or* a
worktree going bad — so a waiter always re-checks and raises promptly instead
of hanging.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from cerebrum.config.model import Module
from cerebrum.exec import git
from cerebrum.exec.command import run_command
from cerebrum.execute.worktree import WorktreeError


class WorktreePool:
    def __init__(self, repo_root: Path, module: Module, size: int) -> None:
        git.require_git_repo(repo_root)
        self._repo_root = repo_root
        self._parent = Path(tempfile.mkdtemp(prefix="cerebrum-pool-"))
        self._all: list[Path] = []
        self._condition = threading.Condition()
        self._available: list[Path] = []
        self._live = 0
        try:
            for i in range(size):
                worktree_root = self._parent / f"tree-{i}"
                git.worktree_add(repo_root, worktree_root, ref="HEAD")
                self._all.append(worktree_root)
                install_result = run_command(module.install, cwd=worktree_root / module.root)
                if install_result.exit_code != 0:
                    raise WorktreeError(
                        f"module '{module.name}': install failed in pooled worktree "
                        f"(exit {install_result.exit_code}): {module.install}"
                    )
                self._available.append(worktree_root)
                self._live += 1
        except Exception:
            self.close()
            raise

    @contextmanager
    def lease(self) -> Iterator[Path]:
        with self._condition:
            while not self._available and self._live > 0:
                self._condition.wait()
            if self._live <= 0:
                raise WorktreeError("worktree pool exhausted — no worktrees remain")
            worktree_root = self._available.pop()

        broken = False
        try:
            yield worktree_root
        finally:
            try:
                git.discard_changes(worktree_root)
            except git.GitError:
                broken = True
            with self._condition:
                if broken:
                    self._live -= 1
                else:
                    self._available.append(worktree_root)
                self._condition.notify_all()
            if broken:
                git.worktree_remove(self._repo_root, worktree_root)

    def close(self) -> None:
        for worktree_root in self._all:
            git.worktree_remove(self._repo_root, worktree_root)
        shutil.rmtree(self._parent, ignore_errors=True)

    def __enter__(self) -> WorktreePool:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
