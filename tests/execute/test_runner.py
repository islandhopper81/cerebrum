"""Tests for the parallel, pooled multi-target runner.

Deterministic: a target-aware fake operator (no LLM) and a shell content-check
test command (no language runtime), matching #3's lifecycle test pattern. The
two outcome-mix tests below are unchanged from #5 — they still hold under the
new pooled/parallel implementation since their assertions are order-independent.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

from cerebrum.config.model import Runtime
from cerebrum.exec import git
from cerebrum.execute.runner import run_targets
from cerebrum.execute.select import build_target
from cerebrum.execute.worktree import WorktreeError
from cerebrum.generate.operator import MutantProposal, MutationTarget
from tests.support import (
    count_installs,
    init_git_repo,
    make_baseline,
    make_install_counter,
    make_module,
    make_patch,
)

_WINDOWS = os.name == "nt"

_SOURCE = 'VALUE = "EXPECTED"\nOTHER = "keepme"\n'


def _grep_cmd() -> str:
    return "findstr EXPECTED app.py" if _WINDOWS else "grep -q EXPECTED app.py"


def _sleep_cmd() -> str:
    return "ping 127.0.0.1 -n 6 > NUL" if _WINDOWS else "sleep 5"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    init_git_repo(repo, {"app.py": _SOURCE})
    return repo


def _worktree_count(repo: Path) -> int:
    out = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.count("worktree ")


class _TargetAwareOperator:
    """Returns a different (or no) proposal depending on the target's line, so a
    single run can exercise a mix of outcomes."""

    def __init__(self, proposals: dict[int, MutantProposal | None]) -> None:
        self._proposals = proposals

    def propose(self, target: MutationTarget) -> MutantProposal | None:
        return self._proposals.get(target.line)


def _proposal(new_source: str) -> MutantProposal:
    return MutantProposal(
        diff=make_patch("app.py", _SOURCE, new_source),
        mutation_type="logic",
        rationale="test mutant",
        equivalent=False,
    )


def test_run_targets_produces_mixed_outcomes_and_records(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    module = make_module(install="echo installing", test=_grep_cmd())
    baseline = make_baseline({(repo / "app.py").resolve(): {1, 2}})
    operator = _TargetAwareOperator(
        {
            1: _proposal('VALUE = "BROKEN"\nOTHER = "keepme"\n'),  # kills
            2: _proposal('VALUE = "EXPECTED"\nOTHER = "changed"\n'),  # survives
        }
    )
    targets = [
        build_target((repo / "app.py").resolve(), 1, repo, "python"),
        build_target((repo / "app.py").resolve(), 2, repo, "python"),
    ]

    records = run_targets(module, repo, baseline, Runtime(), operator, targets)

    assert {r.line: r.status for r in records} == {1: "KILLED", 2: "SURVIVED"}

    out = repo / ".cerebrum" / "mutants.jsonl"
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert {json.loads(line)["line"] for line in lines} == {1, 2}


def test_run_targets_skips_no_mutant_produced_without_aborting(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    module = make_module(install="echo installing", test=_grep_cmd())
    baseline = make_baseline({(repo / "app.py").resolve(): {1, 2}})
    operator = _TargetAwareOperator(
        {
            1: None,  # operator declines -> NoMutantProduced, skipped
            2: _proposal('VALUE = "BROKEN"\nOTHER = "keepme"\n'),
        }
    )
    targets = [
        build_target((repo / "app.py").resolve(), 1, repo, "python"),
        build_target((repo / "app.py").resolve(), 2, repo, "python"),
    ]

    records = run_targets(module, repo, baseline, Runtime(), operator, targets)

    assert [r.line for r in records] == [2]
    assert records[0].status == "KILLED"


def test_run_targets_reuses_worktree_when_pool_smaller_than_target_count(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    install_cmd, counter = make_install_counter(tmp_path)
    module = make_module(install=install_cmd, test=_grep_cmd())
    baseline = make_baseline({(repo / "app.py").resolve(): {1, 2}})
    operator = _TargetAwareOperator(
        {
            1: _proposal('VALUE = "BROKEN"\nOTHER = "keepme"\n'),
            2: _proposal('VALUE = "EXPECTED"\nOTHER = "changed"\n'),
        }
    )
    targets = [
        build_target((repo / "app.py").resolve(), 1, repo, "python"),
        build_target((repo / "app.py").resolve(), 2, repo, "python"),
    ]

    records = run_targets(module, repo, baseline, Runtime(parallelism=1), operator, targets)

    assert {r.line: r.status for r in records} == {1: "KILLED", 2: "SURVIVED"}
    assert count_installs(counter) == 1  # one worktree, reused for both targets


def test_run_targets_timeout_via_pooled_path(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    module = make_module(install="echo installing", test=_sleep_cmd())
    baseline = make_baseline({(repo / "app.py").resolve(): {1}}, test_duration_seconds=0.1)
    operator = _TargetAwareOperator({1: _proposal('VALUE = "BROKEN"\nOTHER = "keepme"\n')})
    targets = [build_target((repo / "app.py").resolve(), 1, repo, "python")]

    records = run_targets(
        module, repo, baseline, Runtime(test_timeout_multiplier=1), operator, targets
    )

    assert records[0].status == "TIMEOUT"


def test_run_targets_propagates_pool_startup_failure_without_leaking_worktrees(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    module = make_module(install="exit 3", test=_grep_cmd())
    baseline = make_baseline({(repo / "app.py").resolve(): {1}})
    operator = _TargetAwareOperator({1: _proposal('VALUE = "BROKEN"\nOTHER = "keepme"\n')})
    targets = [build_target((repo / "app.py").resolve(), 1, repo, "python")]

    with pytest.raises(WorktreeError):
        run_targets(module, repo, baseline, Runtime(), operator, targets)

    assert _worktree_count(repo) == 1


def test_run_targets_survives_a_revert_failure_mid_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    module = make_module(install="echo installing", test=_grep_cmd())
    baseline = make_baseline({(repo / "app.py").resolve(): {1, 2}})
    operator = _TargetAwareOperator(
        {
            1: _proposal('VALUE = "BROKEN"\nOTHER = "keepme"\n'),
            2: _proposal('VALUE = "EXPECTED"\nOTHER = "changed"\n'),
        }
    )
    targets = [
        build_target((repo / "app.py").resolve(), 1, repo, "python"),
        build_target((repo / "app.py").resolve(), 2, repo, "python"),
    ]

    original = git.discard_changes
    lock = threading.Lock()
    calls = {"n": 0}

    def _fail_once(worktree_root: Path) -> None:
        with lock:
            calls["n"] += 1
            first = calls["n"] == 1
        if first:
            raise git.GitError("simulated")
        original(worktree_root)

    monkeypatch.setattr("cerebrum.execute.pool.git.discard_changes", _fail_once)

    records = run_targets(module, repo, baseline, Runtime(), operator, targets)

    assert {r.line: r.status for r in records} == {1: "KILLED", 2: "SURVIVED"}


def test_run_targets_persists_completed_records_before_exhaustion_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    module = make_module(install="echo installing", test=_grep_cmd())
    baseline = make_baseline({(repo / "app.py").resolve(): {1, 2}})
    operator = _TargetAwareOperator(
        {
            1: _proposal('VALUE = "BROKEN"\nOTHER = "keepme"\n'),
            2: _proposal('VALUE = "EXPECTED"\nOTHER = "changed"\n'),
        }
    )
    targets = [
        build_target((repo / "app.py").resolve(), 1, repo, "python"),
        build_target((repo / "app.py").resolve(), 2, repo, "python"),
    ]

    def _always_broken(worktree_root: Path) -> None:
        raise git.GitError("simulated")

    monkeypatch.setattr("cerebrum.execute.pool.git.discard_changes", _always_broken)

    # A single-worktree pool: after target 1's worktree fails to revert, the
    # pool is fully exhausted, so target 2's lease raises and aborts the run.
    with pytest.raises(WorktreeError):
        run_targets(module, repo, baseline, Runtime(parallelism=1), operator, targets)

    out = repo / ".cerebrum" / "mutants.jsonl"
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    persisted = json.loads(lines[0])
    assert persisted["line"] == 1
    assert persisted["status"] == "KILLED"
