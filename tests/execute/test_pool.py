"""Unit tests for the reusable worktree pool."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

from cerebrum.exec import git
from cerebrum.execute.pool import WorktreePool
from cerebrum.execute.worktree import WorktreeError
from tests.support import count_installs, init_git_repo, make_install_counter, make_module


def _worktree_count(repo: Path) -> int:
    out = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.count("worktree ")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    init_git_repo(repo, {"a.txt": "one\n"})
    return repo


def test_pool_creates_size_worktrees_and_installs_once_each(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    install_cmd, counter = make_install_counter(tmp_path)
    module = make_module(install=install_cmd)

    with WorktreePool(repo, module, size=3):
        assert _worktree_count(repo) == 4  # main checkout + 3 pooled

    assert count_installs(counter) == 3
    assert _worktree_count(repo) == 1  # cleaned up on close


def test_pool_reuses_worktrees_across_many_leases(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    install_cmd, counter = make_install_counter(tmp_path)
    module = make_module(install=install_cmd)

    with WorktreePool(repo, module, size=2) as pool:
        for _ in range(5):
            with pool.lease():
                pass

    assert count_installs(counter) == 2  # never re-installed on reuse


def test_pool_creation_failure_cleans_up_and_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    module = make_module(install="exit 3")

    with pytest.raises(WorktreeError):
        WorktreePool(repo, module, size=2)

    assert _worktree_count(repo) == 1  # no leaked worktrees


def test_pool_lease_result_survives_a_revert_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    module = make_module()
    pool = WorktreePool(repo, module, size=1)
    try:
        monkeypatch.setattr(
            "cerebrum.execute.pool.git.discard_changes",
            lambda worktree_root: (_ for _ in ()).throw(git.GitError("simulated")),
        )

        def _use_pool() -> str:
            with pool.lease():
                return "mutant-result"

        assert _use_pool() == "mutant-result"
    finally:
        pool.close()


def test_pool_drops_broken_worktree_and_continues_with_reduced_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    module = make_module()
    pool = WorktreePool(repo, module, size=2)
    try:
        original = git.discard_changes
        calls = {"n": 0}

        def _fail_once(worktree_root: Path) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise git.GitError("simulated")
            original(worktree_root)

        monkeypatch.setattr("cerebrum.execute.pool.git.discard_changes", _fail_once)

        with pool.lease():
            pass  # first release triggers the simulated failure -> dropped

        assert _worktree_count(repo) == 2  # main checkout + 1 remaining pooled

        with pool.lease():
            pass  # remaining worktree still usable
    finally:
        pool.close()


def test_pool_raises_on_exhaustion_instead_of_hanging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    module = make_module()

    def _always_broken(worktree_root: Path) -> None:
        raise git.GitError("simulated")

    monkeypatch.setattr("cerebrum.execute.pool.git.discard_changes", _always_broken)

    pool = WorktreePool(repo, module, size=1)
    try:
        with pool.lease():
            pass  # revert fails -> pool now exhausted

        outcome: dict[str, BaseException] = {}

        def _attempt() -> None:
            try:
                with pool.lease():
                    pass
            except BaseException as exc:  # noqa: BLE001
                outcome["error"] = exc

        thread = threading.Thread(target=_attempt, daemon=True)
        thread.start()
        thread.join(timeout=5)

        assert not thread.is_alive(), "lease() hung instead of raising on exhaustion"
        assert isinstance(outcome.get("error"), WorktreeError)
    finally:
        pool.close()
