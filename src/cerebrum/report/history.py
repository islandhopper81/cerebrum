"""SQLite-backed run history.

One row per run in ``runs``, one row per survivor per run in ``survivors`` —
this is what makes cross-run trend queries (average score, recurring
unaddressed survivors) possible without re-parsing every run's JSONL. Uses
stdlib ``sqlite3``; no new dependency.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cerebrum.execute.models import MutantRecord
from cerebrum.report.models import RunSummary

DB_DIRNAME = ".cerebrum"
DB_FILENAME = "history.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    module TEXT NOT NULL,
    strategy TEXT NOT NULL,
    commit_hash TEXT,
    killed INTEGER NOT NULL,
    survived INTEGER NOT NULL,
    timeout INTEGER NOT NULL,
    build_error INTEGER NOT NULL,
    no_coverage INTEGER NOT NULL,
    mutation_score REAL,
    avg_survivor_severity REAL,
    duration_seconds REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS survivors (
    run_id TEXT NOT NULL,
    file TEXT NOT NULL,
    line INTEGER NOT NULL,
    mutation_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    rationale TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);
"""


def init_db(repo_root: Path) -> Path:
    out_dir = repo_root / DB_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / DB_FILENAME
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return path


def _connect(repo_root: Path) -> sqlite3.Connection:
    return sqlite3.connect(init_db(repo_root))


def record_run(repo_root: Path, summary: RunSummary, records: list[MutantRecord]) -> None:
    conn = _connect(repo_root)
    try:
        conn.execute(
            "INSERT INTO runs (run_id, started_at, module, strategy, commit_hash, "
            "killed, survived, timeout, build_error, no_coverage, mutation_score, "
            "avg_survivor_severity, duration_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                summary.run_id,
                summary.started_at,
                summary.module,
                summary.strategy,
                summary.commit,
                summary.killed,
                summary.survived,
                summary.timeout,
                summary.build_error,
                summary.no_coverage,
                summary.mutation_score,
                summary.avg_survivor_severity,
                summary.duration_seconds,
            ),
        )
        conn.executemany(
            "INSERT INTO survivors (run_id, file, line, mutation_type, severity, rationale) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (summary.run_id, r.file, r.line, r.mutation_type, r.severity, r.rationale)
                for r in records
                if r.status == "SURVIVED"
            ],
        )
        conn.commit()
    finally:
        conn.close()


def trend(repo_root: Path, module: str, limit: int = 20) -> list[RunSummary]:
    conn = _connect(repo_root)
    try:
        rows = conn.execute(
            "SELECT run_id, started_at, module, strategy, commit_hash, killed, survived, "
            "timeout, build_error, no_coverage, mutation_score, avg_survivor_severity, "
            "duration_seconds FROM runs WHERE module = ? ORDER BY started_at DESC LIMIT ?",
            (module, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        RunSummary(
            run_id=row[0],
            started_at=row[1],
            module=row[2],
            strategy=row[3],
            commit=row[4],
            killed=row[5],
            survived=row[6],
            timeout=row[7],
            build_error=row[8],
            no_coverage=row[9],
            mutation_score=row[10],
            avg_survivor_severity=row[11],
            duration_seconds=row[12],
        )
        for row in rows
    ]


def recurring_survivors(
    repo_root: Path, module: str, run_id: str
) -> dict[tuple[str, int], int]:
    """For each survivor in ``run_id``, count consecutive runs (including this
    one) at the same ``file, line`` — walking backward through the module's
    prior runs until the streak breaks."""
    conn = _connect(repo_root)
    try:
        run_ids = [
            row[0]
            for row in conn.execute(
                "SELECT run_id FROM runs WHERE module = ? ORDER BY started_at ASC", (module,)
            ).fetchall()
        ]
        if run_id not in run_ids:
            return {}
        target_index = run_ids.index(run_id)

        survivor_sets: dict[str, set[tuple[str, int]]] = {}
        for rid in run_ids[: target_index + 1]:
            rows = conn.execute(
                "SELECT file, line FROM survivors WHERE run_id = ?", (rid,)
            ).fetchall()
            survivor_sets[rid] = {(file, line) for file, line in rows}
    finally:
        conn.close()

    counts: dict[tuple[str, int], int] = {}
    for survivor in survivor_sets[run_id]:
        streak = 1
        idx = target_index - 1
        while idx >= 0 and survivor in survivor_sets[run_ids[idx]]:
            streak += 1
            idx -= 1
        counts[survivor] = streak
    return counts
