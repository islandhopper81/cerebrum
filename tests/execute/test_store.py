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
        severity="high",
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
        "severity": "high",
    }


def test_append_is_additive(tmp_path: Path) -> None:
    append_record(tmp_path, _record(line=1))
    out = append_record(tmp_path, _record(line=2))

    lines = out.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["line"] for line in lines] == [1, 2]


def test_append_without_run_id_uses_legacy_flat_file(tmp_path: Path) -> None:
    out = append_record(tmp_path, _record())
    assert out == tmp_path / ".cerebrum" / "mutants.jsonl"


def test_append_with_run_id_writes_under_runs_directory(tmp_path: Path) -> None:
    out = append_record(tmp_path, _record(), run_id="20260101T000000Z-abc123")

    assert out == tmp_path / ".cerebrum" / "runs" / "20260101T000000Z-abc123" / "mutants.jsonl"
    assert out.exists()


def test_different_run_ids_write_to_separate_files(tmp_path: Path) -> None:
    out_a = append_record(tmp_path, _record(line=1), run_id="run-a")
    out_b = append_record(tmp_path, _record(line=2), run_id="run-b")

    assert out_a != out_b
    assert json.loads(out_a.read_text(encoding="utf-8").splitlines()[0])["line"] == 1
    assert json.loads(out_b.read_text(encoding="utf-8").splitlines()[0])["line"] == 2
