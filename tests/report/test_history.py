"""Unit tests for the SQLite-backed run history."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cerebrum.execute.models import MutantRecord
from cerebrum.report.history import (
    DB_DIRNAME,
    DB_FILENAME,
    init_db,
    record_run,
    recurring_survivors,
    trend,
)
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
        "covered_lines": 80,
        "instrumented_lines": 100,
        "coverage_pct": 0.8,
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


def test_init_db_adds_coverage_columns_to_preexisting_db(tmp_path: Path) -> None:
    # Simulate a DB created before coverage columns existed.
    out_dir = tmp_path / DB_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / DB_FILENAME
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, "
        "module TEXT NOT NULL, strategy TEXT NOT NULL, commit_hash TEXT, "
        "killed INTEGER NOT NULL, survived INTEGER NOT NULL, timeout INTEGER NOT NULL, "
        "build_error INTEGER NOT NULL, no_coverage INTEGER NOT NULL, "
        "mutation_score REAL, avg_survivor_severity REAL, duration_seconds REAL NOT NULL);"
    )
    conn.commit()
    conn.close()

    init_db(tmp_path)  # should ALTER the existing table, not error

    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    conn.close()
    assert {"covered_lines", "instrumented_lines", "coverage_pct"} <= columns

    # And a run recorded against the migrated DB round-trips its coverage.
    record_run(tmp_path, _summary("run-x", "2026-01-01T00:00:00+00:00"), [])
    assert trend(tmp_path, "backend")[0].coverage_pct == 0.8


def test_record_run_and_trend_round_trip(tmp_path: Path) -> None:
    summary = _summary("run-1", "2026-01-01T00:00:00+00:00")
    record_run(tmp_path, summary, [_survivor_record("a.py", 5)])

    runs = trend(tmp_path, "backend")

    assert len(runs) == 1
    assert runs[0].run_id == "run-1"
    assert runs[0].mutation_score == 0.75
    assert runs[0].avg_survivor_severity == 2.0
    assert runs[0].covered_lines == 80
    assert runs[0].instrumented_lines == 100
    assert runs[0].coverage_pct == 0.8


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
