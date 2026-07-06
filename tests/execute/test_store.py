"""Unit tests for JSONL persistence of mutant records."""

from __future__ import annotations

import json
from pathlib import Path

from cerebrum.execute.models import MutantRecord
from cerebrum.execute.store import append_record


def _record(status: str = "KILLED", line: int = 3) -> MutantRecord:
    return MutantRecord(
        file="pkg/mod.py",
        line=line,
        diff="--- a/pkg/mod.py\n+++ b/pkg/mod.py\n",
        mutation_type="conditional",
        status=status,  # type: ignore[arg-type]
        covering_tests="pytest",
        rationale="flipped a comparison",
        duration_seconds=1.25,
    )


def test_append_creates_file_and_round_trips(tmp_path: Path) -> None:
    out = append_record(tmp_path, _record())

    assert out == tmp_path / ".cerebrum" / "mutants.jsonl"
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    data = json.loads(lines[0])
    assert data == {
        "file": "pkg/mod.py",
        "line": 3,
        "diff": "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n",
        "mutation_type": "conditional",
        "status": "KILLED",
        "covering_tests": "pytest",
        "rationale": "flipped a comparison",
        "duration_seconds": 1.25,
    }


def test_append_is_additive(tmp_path: Path) -> None:
    append_record(tmp_path, _record(line=1))
    out = append_record(tmp_path, _record(line=2))

    lines = out.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["line"] for line in lines] == [1, 2]
