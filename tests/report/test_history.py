"""Unit tests for the SQLite-backed run history."""

from __future__ import annotations

from pathlib import Path

from cerebrum.execute.models import MutantRecord
from cerebrum.report.history import init_db, record_run, recurring_survivors, trend
from cerebrum.report.models import RunSummary


def _summary(
    run_id: str, started_at: str, module: str = "backend", **overrides: object
) -> RunSummary:
    defaults: dict[str, object] = {
        "run_id": run_id,
        "started_at": started_at,
        "module": module,
        "strategy": "coverage",
        "commit": "abc123",
        "killed": 3,
        "survived": 1,
        "timeout": 0,
        "build_error": 0,
        "no_coverage": 0,
        "mutation_score": 0.75,
        "avg_survivor_severity": 2.0,
        "duration_seconds": 12.5,
    }
    defaults.update(overrides)
    return RunSummary(**defaults)  # type: ignore[arg-type]


def _survivor_record(file: str, line: int) -> MutantRecord:
    return MutantRecord(
        file=file,
        line=line,
        diff="",
        mutation_type="logic",
        status="SURVIVED",
        covering_tests="pytest",
        rationale="",
        duration_seconds=0.1,
        severity="high",
    )


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    path1 = init_db(tmp_path)
    path2 = init_db(tmp_path)
    assert path1 == path2
    assert path1.exists()


def test_record_run_and_trend_round_trip(tmp_path: Path) -> None:
    summary = _summary("run-1", "2026-01-01T00:00:00+00:00")
    record_run(tmp_path, summary, [_survivor_record("a.py", 5)])

    runs = trend(tmp_path, "backend")

    assert len(runs) == 1
    assert runs[0].run_id == "run-1"
    assert runs[0].mutation_score == 0.75
    assert runs[0].avg_survivor_severity == 2.0


def test_trend_orders_most_recent_first_and_respects_limit(tmp_path: Path) -> None:
    record_run(tmp_path, _summary("run-1", "2026-01-01T00:00:00+00:00"), [])
    record_run(tmp_path, _summary("run-2", "2026-01-02T00:00:00+00:00"), [])
    record_run(tmp_path, _summary("run-3", "2026-01-03T00:00:00+00:00"), [])

    runs = trend(tmp_path, "backend", limit=2)

    assert [r.run_id for r in runs] == ["run-3", "run-2"]


def test_trend_is_scoped_per_module(tmp_path: Path) -> None:
    record_run(tmp_path, _summary("run-a", "2026-01-01T00:00:00+00:00", module="backend"), [])
    record_run(tmp_path, _summary("run-b", "2026-01-01T00:00:00+00:00", module="frontend"), [])

    assert [r.run_id for r in trend(tmp_path, "backend")] == ["run-a"]
    assert [r.run_id for r in trend(tmp_path, "frontend")] == ["run-b"]


def test_recurring_survivors_counts_a_streak(tmp_path: Path) -> None:
    record_run(
        tmp_path,
        _summary("run-1", "2026-01-01T00:00:00+00:00"),
        [_survivor_record("a.py", 5)],
    )
    record_run(
        tmp_path,
        _summary("run-2", "2026-01-02T00:00:00+00:00"),
        [_survivor_record("a.py", 5)],
    )
    record_run(
        tmp_path,
        _summary("run-3", "2026-01-03T00:00:00+00:00"),
        [_survivor_record("a.py", 5)],
    )

    counts = recurring_survivors(tmp_path, "backend", "run-3")

    assert counts[("a.py", 5)] == 3


def test_recurring_survivors_resets_after_a_gap(tmp_path: Path) -> None:
    record_run(
        tmp_path,
        _summary("run-1", "2026-01-01T00:00:00+00:00"),
        [_survivor_record("a.py", 5)],
    )
    record_run(tmp_path, _summary("run-2", "2026-01-02T00:00:00+00:00"), [])  # gap, not a survivor
    record_run(
        tmp_path,
        _summary("run-3", "2026-01-03T00:00:00+00:00"),
        [_survivor_record("a.py", 5)],
    )

    counts = recurring_survivors(tmp_path, "backend", "run-3")

    assert counts[("a.py", 5)] == 1  # streak broke at run-2, so this is "new again"
