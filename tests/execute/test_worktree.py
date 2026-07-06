"""Unit tests for the mutation worktree context manager."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from cerebrum.execute.worktree import WorktreeError, mutation_worktree
from tests.support import init_git_repo, make_module

_WINDOWS = os.name == "nt"


def _fail_cmd() -> str:
    return "exit 3"


def _worktree_count(repo: Path) -> int:
    out = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.count("worktree ")


def test_worktree_yields_committed_files_and_cleans_up(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"app.py": "VALUE = 1\n"})
    module = make_module(install="echo installing")

    with mutation_worktree(tmp_path, module) as worktree_root:
        assert worktree_root.exists()
        assert (worktree_root / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
        assert _worktree_count(tmp_path) == 2

    assert not worktree_root.exists()
    assert _worktree_count(tmp_path) == 1


def test_install_failure_raises_and_still_cleans_up(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"app.py": "VALUE = 1\n"})
    module = make_module(install=_fail_cmd())

    with pytest.raises(WorktreeError):
        with mutation_worktree(tmp_path, module):
            pass

    assert _worktree_count(tmp_path) == 1
