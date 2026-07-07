"""Unit tests for the git wrappers used by the mutant lifecycle."""

from __future__ import annotations

import subprocess
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


def _commit_all(repo: Path, message: str = "change") -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True
    )


def test_changed_lines_reports_added_lines(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.py": "one\n"})
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    _commit_all(tmp_path)

    changed = git.changed_lines(tmp_path, "HEAD~1..HEAD")

    assert changed == {(tmp_path / "a.py").resolve(): {2, 3}}


def test_changed_lines_reports_modified_lines(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.py": "one\ntwo\nthree\n"})
    (tmp_path / "a.py").write_text("one\nCHANGED\nthree\n", encoding="utf-8")
    _commit_all(tmp_path)

    changed = git.changed_lines(tmp_path, "HEAD~1..HEAD")

    assert changed == {(tmp_path / "a.py").resolve(): {2}}


def test_changed_lines_pure_deletion_contributes_nothing(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.py": "one\ntwo\nthree\n"})
    (tmp_path / "a.py").write_text("one\nthree\n", encoding="utf-8")
    _commit_all(tmp_path)

    changed = git.changed_lines(tmp_path, "HEAD~1..HEAD")

    assert changed == {}


def test_changed_lines_multi_file_diff(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.py": "one\n", "b.py": "uno\n"})
    (tmp_path / "a.py").write_text("one\ntwo\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("uno\ndos\n", encoding="utf-8")
    _commit_all(tmp_path)

    changed = git.changed_lines(tmp_path, "HEAD~1..HEAD")

    assert changed == {
        (tmp_path / "a.py").resolve(): {2},
        (tmp_path / "b.py").resolve(): {2},
    }


def test_changed_lines_bad_range_raises(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.py": "one\n"})
    with pytest.raises(git.GitError):
        git.changed_lines(tmp_path, "nonexistent-ref~1..nonexistent-ref")


def test_discard_changes_restores_tracked_file(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.txt": "one\n"})
    (tmp_path / "a.txt").write_text("mutated\n", encoding="utf-8")

    git.discard_changes(tmp_path)

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "one\n"


def test_current_commit_returns_head_hash_in_a_repo(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.txt": "one\n"})

    commit = git.current_commit(tmp_path)

    assert commit is not None
    assert len(commit) == 40  # full sha
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert commit == out


def test_current_commit_returns_none_outside_a_repo(tmp_path: Path) -> None:
    assert git.current_commit(tmp_path) is None


def test_discard_changes_removes_untracked_file(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.txt": "one\n"})
    (tmp_path / "new_file.txt").write_text("surprise\n", encoding="utf-8")

    git.discard_changes(tmp_path)

    assert not (tmp_path / "new_file.txt").exists()
