"""Unit tests for the git wrappers used by the mutant lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

from cerebrum.exec import git
from tests.support import init_git_repo, make_patch


def test_require_git_repo_passes_in_repo(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.txt": "one\n"})
    git.require_git_repo(tmp_path)  # does not raise


def test_require_git_repo_raises_outside_repo(tmp_path: Path) -> None:
    with pytest.raises(git.GitError):
        git.require_git_repo(tmp_path)


def test_apply_check_true_for_matching_patch(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.txt": "one\n"})
    diff = make_patch("a.txt", "one\n", "two\n")
    assert git.apply_check(tmp_path, diff) is True


def test_apply_check_false_for_conflicting_patch(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.txt": "one\n"})
    diff = make_patch("a.txt", "NOT-THE-CONTENT\n", "two\n")
    assert git.apply_check(tmp_path, diff) is False


def test_apply_mutates_the_file(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.txt": "one\n"})
    git.apply(tmp_path, make_patch("a.txt", "one\n", "two\n"))
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "two\n"


def test_apply_raises_on_conflict(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.txt": "one\n"})
    with pytest.raises(git.GitError):
        git.apply(tmp_path, make_patch("a.txt", "NOPE\n", "two\n"))


def test_worktree_add_and_remove(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo, {"a.txt": "one\n"})
    wt = tmp_path / "wt"

    git.worktree_add(repo, wt)
    assert (wt / "a.txt").read_text(encoding="utf-8") == "one\n"

    git.worktree_remove(repo, wt)
    assert not wt.exists()
