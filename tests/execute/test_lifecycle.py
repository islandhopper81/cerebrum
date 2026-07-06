"""End-to-end tests for the single-mutant lifecycle.

Deterministic: no LLM (a fake operator returns a preset patch) and no language
runtime (the fixture module's ``test`` command is a shell content check). This
exercises the real worktree/apply/classify path.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from cerebrum.config.model import Runtime
from cerebrum.execute.lifecycle import NoMutantProduced, run_mutant
from cerebrum.execute.select import select_target
from cerebrum.generate.operator import MutantProposal
from tests.support import (
    FakeOperator,
    init_git_repo,
    make_baseline,
    make_module,
    make_patch,
)

_WINDOWS = os.name == "nt"

_SOURCE = 'VALUE = "EXPECTED"\nOTHER = "keepme"\n'


def _grep_cmd() -> str:
    # exit 0 iff the file still contains EXPECTED
    return "findstr EXPECTED app.py" if _WINDOWS else "grep -q EXPECTED app.py"


def _sleep_cmd() -> str:
    return "ping 127.0.0.1 -n 6 > NUL" if _WINDOWS else "sleep 5"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    init_git_repo(repo, {"app.py": _SOURCE})
    return repo


def _covered(repo: Path, lines: set[int]) -> dict[Path, set[int]]:
    return {(repo / "app.py").resolve(): lines}


def _proposal(new_source: str) -> MutantProposal:
    return MutantProposal(
        diff=make_patch("app.py", _SOURCE, new_source),
        mutation_type="logic",
        rationale="test mutant",
        equivalent=False,
    )


def _worktree_count(repo: Path) -> int:
    out = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.count("worktree ")


def test_killed_when_mutation_breaks_a_checked_value(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    module = make_module(install="echo installing", test=_grep_cmd())
    baseline = make_baseline(_covered(repo, {1, 2}))
    operator = FakeOperator(_proposal('VALUE = "BROKEN"\nOTHER = "keepme"\n'))
    target = select_target(baseline, module, repo, file="app.py", line=1)
    assert target is not None

    record = run_mutant(module, repo, baseline, Runtime(), operator, target)

    assert record.status == "KILLED"
    assert record.file == "app.py"
    assert record.line == 1
    assert _worktree_count(repo) == 1  # cleaned up


def test_survived_when_mutation_is_not_checked(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    module = make_module(install="echo installing", test=_grep_cmd())
    baseline = make_baseline(_covered(repo, {1, 2}))
    operator = FakeOperator(_proposal('VALUE = "EXPECTED"\nOTHER = "changed"\n'))
    target = select_target(baseline, module, repo, file="app.py", line=2)
    assert target is not None

    record = run_mutant(module, repo, baseline, Runtime(), operator, target)

    assert record.status == "SURVIVED"
    assert _worktree_count(repo) == 1


def test_build_error_when_patch_will_not_apply(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    module = make_module(install="echo installing", test=_grep_cmd())
    baseline = make_baseline(_covered(repo, {1}))
    bad = MutantProposal(
        diff=make_patch("app.py", "does-not-match\n", "replacement\n"),
        mutation_type="logic",
        rationale="unappliable",
        equivalent=False,
    )
    operator = FakeOperator(bad)
    target = select_target(baseline, module, repo, file="app.py", line=1)
    assert target is not None

    record = run_mutant(module, repo, baseline, Runtime(), operator, target)

    assert record.status == "BUILD_ERROR"
    assert record.duration_seconds == 0.0
    assert _worktree_count(repo) == 1


def test_timeout_when_test_runs_too_long(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    module = make_module(install="echo installing", test=_sleep_cmd())
    baseline = make_baseline(_covered(repo, {1}), test_duration_seconds=0.1)
    operator = FakeOperator(_proposal('VALUE = "BROKEN"\nOTHER = "keepme"\n'))
    target = select_target(baseline, module, repo, file="app.py", line=1)
    assert target is not None

    record = run_mutant(
        module, repo, baseline, Runtime(test_timeout_multiplier=1), operator, target
    )

    assert record.status == "TIMEOUT"
    assert _worktree_count(repo) == 1


def test_no_coverage_short_circuits_without_calling_operator(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    module = make_module(install="echo installing", test=_grep_cmd())
    baseline = make_baseline(_covered(repo, {1}))
    operator = FakeOperator(_proposal('VALUE = "BROKEN"\nOTHER = "keepme"\n'))
    target = select_target(baseline, module, repo, file="app.py", line=99)
    assert target is not None

    record = run_mutant(module, repo, baseline, Runtime(), operator, target)

    assert record.status == "NO_COVERAGE"
    assert operator.calls is None  # never asked to generate


def test_equivalent_proposal_raises_no_mutant_produced(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    module = make_module(install="echo installing", test=_grep_cmd())
    baseline = make_baseline(_covered(repo, {1}))
    equivalent = MutantProposal(
        diff=make_patch("app.py", _SOURCE, 'VALUE = "BROKEN"\nOTHER = "keepme"\n'),
        mutation_type="logic",
        rationale="equivalent",
        equivalent=True,
    )
    operator = FakeOperator(equivalent)
    target = select_target(baseline, module, repo, file="app.py", line=1)
    assert target is not None

    with pytest.raises(NoMutantProduced):
        run_mutant(module, repo, baseline, Runtime(), operator, target)

    assert _worktree_count(repo) == 1


def test_none_proposal_raises_no_mutant_produced(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    module = make_module(install="echo installing", test=_grep_cmd())
    baseline = make_baseline(_covered(repo, {1}))
    operator = FakeOperator(None)
    target = select_target(baseline, module, repo, file="app.py", line=1)
    assert target is not None

    with pytest.raises(NoMutantProduced):
        run_mutant(module, repo, baseline, Runtime(), operator, target)
