"""Unit tests for the pure survivor-report builder."""

from __future__ import annotations

from cerebrum.execute.models import MutantRecord, MutantStatus
from cerebrum.report.survivors import build_survivor_report


def _record(status: MutantStatus, file: str = "a.py", line: int = 1) -> MutantRecord:
    return MutantRecord(
        file=file,
        line=line,
        diff="--- a/a.py\n+++ b/a.py\n",
        mutation_type="logic",
        status=status,
        covering_tests="pytest",
        rationale="flipped a comparison",
        duration_seconds=0.1,
        severity="high",
    )


def test_build_survivor_report_filters_to_survived_only() -> None:
    records = [
        _record("SURVIVED", line=1),
        _record("KILLED", line=2),
        _record("BUILD_ERROR", line=3),
    ]

    report = build_survivor_report(records, recurrence={})

    assert [e.line for e in report] == [1]


def test_build_survivor_report_joins_recurrence_counts() -> None:
    records = [_record("SURVIVED", file="a.py", line=5)]

    report = build_survivor_report(records, recurrence={("a.py", 5): 4})

    assert report[0].consecutive_runs == 4


def test_build_survivor_report_defaults_recurrence_to_one() -> None:
    records = [_record("SURVIVED", file="a.py", line=5)]

    report = build_survivor_report(records, recurrence={})

    assert report[0].consecutive_runs == 1


def test_build_survivor_report_suggested_test_starts_none() -> None:
    records = [_record("SURVIVED")]

    report = build_survivor_report(records, recurrence={})

    assert report[0].suggested_test is None
