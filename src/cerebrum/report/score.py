"""Score a set of mutant records.

``mutation_score = KILLED / (KILLED + SURVIVED)`` — ``BUILD_ERROR`` and
``NO_COVERAGE`` are invalid mutants, not kills, and are excluded from the
denominator entirely.
"""

from __future__ import annotations

from cerebrum.execute.models import MutantRecord
from cerebrum.generate.operator import Severity

SEVERITY_WEIGHT: dict[Severity, int] = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def compute_score(records: list[MutantRecord]) -> float | None:
    killed = sum(1 for r in records if r.status == "KILLED" or r.status == "TIMEOUT")
    survived = sum(1 for r in records if r.status == "SURVIVED")
    total = killed + survived
    if total == 0:
        return None
    return killed / total


def average_survivor_severity(records: list[MutantRecord]) -> float | None:
    weights = [
        SEVERITY_WEIGHT[r.severity]
        for r in records
        if r.status == "SURVIVED" and r.severity in SEVERITY_WEIGHT
    ]
    if not weights:
        return None
    return sum(weights) / len(weights)
