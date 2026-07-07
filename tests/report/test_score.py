"""Unit tests for score and severity aggregation."""

from __future__ import annotations

from cerebrum.execute.models import MutantRecord, MutantStatus
from cerebrum.report.score import average_survivor_severity, compute_score


def _record(status: MutantStatus, severity: str = "medium") -> MutantRecord:
    return MutantRecord(
        file="a.py",
        line=1,
        diff="",
        mutation_type="logic",
        status=status,
        covering_tests="pytest",
        rationale="",
        duration_seconds=0.1,
        severity=severity,
    )


def test_compute_score_excludes_invalid_statuses() -> None:
    records = [
        _record("KILLED"),
        _record("KILLED"),
        _record("SURVIVED"),
        _record("BUILD_ERROR"),
        _record("NO_COVERAGE"),
    ]
    assert compute_score(records) == 2 / 3


def test_compute_score_counts_timeout_as_killed() -> None:
    records = [_record("TIMEOUT"), _record("SURVIVED")]
    assert compute_score(records) == 0.5


def test_compute_score_returns_none_when_no_valid_mutants() -> None:
    assert compute_score([_record("BUILD_ERROR"), _record("NO_COVERAGE")]) is None


def test_compute_score_returns_none_for_empty_list() -> None:
    assert compute_score([]) is None


def test_average_survivor_severity_averages_only_survivors() -> None:
    records = [
        _record("SURVIVED", severity="low"),  # 1
        _record("SURVIVED", severity="critical"),  # 4
        _record("KILLED", severity="critical"),  # excluded
    ]
    assert average_survivor_severity(records) == 2.5


def test_average_survivor_severity_returns_none_with_no_survivors() -> None:
    assert average_survivor_severity([_record("KILLED")]) is None
