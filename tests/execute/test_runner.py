"""Tests for the sequential multi-target runner.

Deterministic: a target-aware fake operator (no LLM) and a shell content-check
test command (no language runtime), matching #3's lifecycle test pattern.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from cerebrum.config.model import Runtime
from cerebrum.execute.runner import run_targets
from cerebrum.execute.select import build_target
from cerebrum.generate.operator import MutantProposal, MutationTarget
from tests.support import init_git_repo, make_baseline, make_module, make_patch

_WINDOWS = os.name == "nt"

_SOURCE = 'VALUE = "EXPECTED"\nOTHER = "keepme"\n'


def _grep_cmd() -> str:
    return "findstr EXPECTED app.py" if _WINDOWS else "grep -q EXPECTED app.py"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    init_git_repo(repo, {"app.py": _SOURCE})
    return repo


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
