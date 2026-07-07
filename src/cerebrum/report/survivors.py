"""Build the survivor report — the deliverable a developer acts on.

Pure: filters ``SURVIVED`` records and joins in recurrence counts. Does not call
an LLM — ``suggested_test`` is filled in by the caller (:mod:`cerebrum.cli`) via
:class:`~cerebrum.report.test_suggester.TestSuggester`, keeping this module
deterministically testable without a network dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

from cerebrum.execute.models import MutantRecord


@dataclass(frozen=True)
class SurvivorEntry:
    file: str
    line: int
    diff: str
    mutation_type: str
    severity: str
    rationale: str
    covering_tests: str
    suggested_test: str | None
    consecutive_runs: int


def build_survivor_report(
    records: list[MutantRecord], recurrence: dict[tuple[str, int], int]
) -> list[SurvivorEntry]:
    return [
        SurvivorEntry(
            file=r.file,
            line=r.line,
            diff=r.diff,
            mutation_type=r.mutation_type,
            severity=r.severity,
            rationale=r.rationale,
            covering_tests=r.covering_tests,
            suggested_test=None,
            consecutive_runs=recurrence.get((r.file, r.line), 1),
        )
        for r in records
        if r.status == "SURVIVED"
    ]
