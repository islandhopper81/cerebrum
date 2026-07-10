"""Engine-internal outputs of the REPORT stage."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    started_at: str
    module: str
    strategy: str
    commit: str | None
    killed: int
    survived: int
    timeout: int
    build_error: int
    no_coverage: int
    mutation_score: float | None
    avg_survivor_severity: float | None
    covered_lines: int | None
    instrumented_lines: int | None
    coverage_pct: float | None
    duration_seconds: float
