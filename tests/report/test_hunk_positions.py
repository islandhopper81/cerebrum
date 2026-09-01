"""Unit tests for the pure hunk-position-mismatch diagnostic."""

from __future__ import annotations

from pathlib import Path

from cerebrum.execute.models import MutantRecord, MutantStatus
from cerebrum.report.hunk_positions import find_position_mismatches


def _record(
    status: MutantStatus,
    file: str = "a.py",
    line: int = 1,
    diff: str = "--- a/a.py\n+++ b/a.py\n",
) -> MutantRecord:
    return MutantRecord(
        file=file,
        line=line,
        diff=diff,
        mutation_type="logic",
        status=status,
        covering_tests="pytest",
        rationale="flipped a comparison",
        duration_seconds=0.1,
        severity="high",
    )


_MISPOSITIONED_DIFF = (
    "--- a/a.py\n"
    "+++ b/a.py\n"
    "@@ -50,4 +50,4 @@\n"  # claims line 50; context actually starts at line 3
    " one\n"
    "-two\n"
    "+TWO\n"
    " three\n"
)

_CORRECTLY_POSITIONED_DIFF = (
    "--- a/a.py\n"
    "+++ b/a.py\n"
    "@@ -3,4 +3,4 @@\n"  # matches where the context actually appears
    " one\n"
    "-two\n"
    "+TWO\n"
    " three\n"
)

_NOT_FOUND_DIFF = (
    "--- a/a.py\n"
    "+++ b/a.py\n"
    "@@ -50,3 +50,3 @@\n"
    " nope\n"
    "-nowhere\n"
    "+NOWHERE\n"
)

_FILE_CONTENT = "zero\ntwo-before\none\ntwo\nthree\nfour\n"


def test_find_position_mismatches_detects_wrong_start_line(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(_FILE_CONTENT, encoding="utf-8")
    records = [_record("BUILD_ERROR", diff=_MISPOSITIONED_DIFF)]

    mismatches = find_position_mismatches(records, tmp_path)

    assert len(mismatches) == 1
    assert mismatches[0].file == "a.py"
    assert mismatches[0].claimed_line == 50
    assert mismatches[0].actual_line == 3


def test_find_position_mismatches_ignores_correctly_positioned_hunk(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(_FILE_CONTENT, encoding="utf-8")
    records = [_record("BUILD_ERROR", diff=_CORRECTLY_POSITIONED_DIFF)]

    mismatches = find_position_mismatches(records, tmp_path)

    assert mismatches == []


def test_find_position_mismatches_ignores_non_build_error_records(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(_FILE_CONTENT, encoding="utf-8")
    records = [
        _record("SURVIVED", diff=_MISPOSITIONED_DIFF),
        _record("KILLED", diff=_MISPOSITIONED_DIFF),
    ]

    mismatches = find_position_mismatches(records, tmp_path)

    assert mismatches == []


def test_find_position_mismatches_reports_none_when_context_not_found(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(_FILE_CONTENT, encoding="utf-8")
    records = [_record("BUILD_ERROR", diff=_NOT_FOUND_DIFF)]

    mismatches = find_position_mismatches(records, tmp_path)

    assert len(mismatches) == 1
    assert mismatches[0].claimed_line == 50
    assert mismatches[0].actual_line is None


def test_find_position_mismatches_skips_missing_file(tmp_path: Path) -> None:
    records = [_record("BUILD_ERROR", file="missing.py", diff=_MISPOSITIONED_DIFF)]

    mismatches = find_position_mismatches(records, tmp_path)

    assert mismatches == []


def test_find_position_mismatches_evaluates_each_record_independently(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(_FILE_CONTENT, encoding="utf-8")
    records = [
        _record("BUILD_ERROR", file="a.py", line=1, diff=_MISPOSITIONED_DIFF),
        _record("BUILD_ERROR", file="a.py", line=2, diff=_CORRECTLY_POSITIONED_DIFF),
    ]

    mismatches = find_position_mismatches(records, tmp_path)

    assert len(mismatches) == 1
    assert mismatches[0].claimed_line == 50
