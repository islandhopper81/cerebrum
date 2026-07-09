"""Unit tests for JSONL persistence of mutant records."""

from __future__ import annotations

import json
from pathlib import Path

from cerebrum.execute.models import MutantRecord
from cerebrum.execute.store import append_record, build_coverage_rows, write_coverage


def _record(
    status: str = "KILLED", line: int = 3, file: str = "pkg/mod.py", severity: str = "high"
) -> MutantRecord:
    return MutantRecord(
        file=file,
        line=line,
        diff="--- a/pkg/mod.py\n+++ b/pkg/mod.py\n",
        mutation_type="conditional",
        status=status,  # type: ignore[arg-type]
        covering_tests="pytest",
        rationale="flipped a comparison",
        duration_seconds=1.25,
        severity=severity,
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


def test_build_coverage_rows_joins_coverage_and_survivors(tmp_path: Path) -> None:
    repo_root = tmp_path
    covered = {
        repo_root / "pkg" / "mod.py": {1, 2, 3, 4},
        repo_root / "pkg" / "other.py": {1},
    }
    instrumented = {
        repo_root / "pkg" / "mod.py": {1, 2, 3, 4, 5, 6, 7, 8},  # 4/8 = 0.5
        repo_root / "pkg" / "other.py": {1, 2},  # 1/2 = 0.5
    }
    records = [
        _record(status="SURVIVED", file="pkg/mod.py", severity="low"),
        _record(status="SURVIVED", file="pkg/mod.py", severity="critical"),
        _record(status="KILLED", file="pkg/mod.py"),
        _record(status="SURVIVED", file="pkg/other.py", severity="medium"),
    ]

    rows = build_coverage_rows(covered, instrumented, records, repo_root)

    assert [r["file"] for r in rows] == ["pkg/mod.py", "pkg/other.py"]  # sorted
    mod = rows[0]
    assert mod["covered_lines"] == 4
    assert mod["instrumented_lines"] == 8
    assert mod["coverage_pct"] == 0.5
    assert mod["survivor_count"] == 2  # KILLED excluded
    assert mod["max_severity"] == "critical"  # worst of low + critical
    other = rows[1]
    assert other["survivor_count"] == 1
    assert other["max_severity"] == "medium"


def test_build_coverage_rows_no_survivors_has_null_severity(tmp_path: Path) -> None:
    instrumented = {tmp_path / "a.py": {1, 2}}
    rows = build_coverage_rows({tmp_path / "a.py": {1}}, instrumented, [], tmp_path)
    assert rows[0]["survivor_count"] == 0
    assert rows[0]["max_severity"] is None
    assert rows[0]["coverage_pct"] == 0.5


def test_write_coverage_writes_json_under_run_dir(tmp_path: Path) -> None:
    rows = [{"file": "a.py", "covered_lines": 1, "instrumented_lines": 2}]
    out = write_coverage(tmp_path, "run-a", rows)

    assert out == tmp_path / ".cerebrum" / "runs" / "run-a" / "coverage.json"
    assert json.loads(out.read_text(encoding="utf-8")) == rows
