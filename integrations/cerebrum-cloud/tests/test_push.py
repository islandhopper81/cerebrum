"""Tests for cerebrum_cloud_push.push."""

from __future__ import annotations

import json
import sqlite3
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from cerebrum_cloud_push.push import (
    _available_columns,
    _function_url,
    _list_run_ids,
    _load_run,
    _load_run_files,
    _load_survivors,
    main,
)

_ALL_COLUMNS = [
    "run_id",
    "module",
    "started_at",
    "strategy",
    "commit_hash",
    "killed",
    "survived",
    "timeout",
    "build_error",
    "no_coverage",
    "mutation_score",
    "avg_survivor_severity",
    "covered_lines",
    "instrumented_lines",
    "coverage_pct",
    "duration_seconds",
]
_LEGACY_COLUMNS = [
    c for c in _ALL_COLUMNS if c not in {"covered_lines", "instrumented_lines", "coverage_pct"}
]


class _FakeResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._data = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _make_db(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    conn = sqlite3.connect(path)
    col_defs = ", ".join(f"{c} TEXT" for c in columns)
    conn.execute(f"CREATE TABLE runs ({col_defs})")
    placeholders = ", ".join("?" for _ in columns)
    for row in rows:
        conn.execute(
            f"INSERT INTO runs ({', '.join(columns)}) VALUES ({placeholders})",
            [row.get(c) for c in columns],
        )
    conn.commit()
    conn.close()


def _row(run_id: str, started_at: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {c: None for c in _ALL_COLUMNS}
    base.update(
        run_id=run_id,
        module="backend",
        started_at=started_at,
        strategy="coverage",
        commit_hash="abc123",
        killed=5,
        survived=1,
        timeout=0,
        build_error=0,
        no_coverage=0,
        mutation_score=0.83,
        avg_survivor_severity="medium",
        covered_lines=10,
        instrumented_lines=12,
        coverage_pct=0.83,
        duration_seconds=1.2,
    )
    base.update(overrides)
    return base


# --- _available_columns / schema tolerance ----------------------------------


def test_available_columns_full_schema(tmp_path: Path) -> None:
    db = tmp_path / "history.sqlite"
    _make_db(db, _ALL_COLUMNS, [_row("r1", "2026-01-01T00:00:00Z")])
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    assert _available_columns(conn) == _ALL_COLUMNS
    conn.close()


def test_available_columns_legacy_schema_omits_coverage_columns(tmp_path: Path) -> None:
    db = tmp_path / "history.sqlite"
    _make_db(db, _LEGACY_COLUMNS, [_row("r1", "2026-01-01T00:00:00Z")])
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cols = _available_columns(conn)
    assert "covered_lines" not in cols
    assert "instrumented_lines" not in cols
    assert "coverage_pct" not in cols
    conn.close()


def test_load_run_on_legacy_schema_fills_missing_coverage_with_none(tmp_path: Path) -> None:
    db = tmp_path / "history.sqlite"
    _make_db(db, _LEGACY_COLUMNS, [_row("r1", "2026-01-01T00:00:00Z")])
    run = _load_run(db, "r1")
    assert run["covered_lines"] is None
    assert run["instrumented_lines"] is None
    assert run["coverage_pct"] is None
    assert run["run_id"] == "r1"


def test_load_run_missing_db_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        _load_run(tmp_path / "missing.sqlite", None)
    assert "no history db" in capsys.readouterr().err


def test_list_run_ids_orders_by_started_at(tmp_path: Path) -> None:
    db = tmp_path / "history.sqlite"
    _make_db(
        db,
        _ALL_COLUMNS,
        [_row("run-2", "2026-01-02T00:00:00Z"), _row("run-1", "2026-01-01T00:00:00Z")],
    )
    assert _list_run_ids(db) == ["run-1", "run-2"]


# --- _load_survivors / _load_run_files --------------------------------------


def test_load_survivors_missing_file_returns_empty(tmp_path: Path) -> None:
    assert _load_survivors(tmp_path / "runs" / "r1") == []


def test_load_run_files_missing_file_returns_empty(tmp_path: Path) -> None:
    assert _load_run_files(tmp_path / "runs" / "r1") == []


def test_load_survivors_filters_status_and_maps_fields(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    lines = [
        json.dumps({"file": "a.py", "line": 1, "status": "KILLED"}),
        json.dumps(
            {
                "file": "b.py",
                "line": 2,
                "status": "SURVIVED",
                "mutation_type": "logic",
                "severity": "high",
                "rationale": "r",
                "diff": "d",
                "covering_tests": "t",
                "suggested_test": "st",
            }
        ),
        "",
    ]
    (run_dir / "mutants.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    survivors = _load_survivors(run_dir)

    assert len(survivors) == 1
    assert survivors[0]["file"] == "b.py"
    assert survivors[0]["line"] == 2
    assert survivors[0]["suggested_test"] == "st"


def test_load_run_files_reads_json_array(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "coverage.json").write_text(
        json.dumps([{"file": "a.py", "covered_lines": 1}]), encoding="utf-8"
    )
    assert _load_run_files(run_dir) == [{"file": "a.py", "covered_lines": 1}]


# --- _function_url -----------------------------------------------------------


def test_function_url_appends_path_to_base() -> None:
    assert _function_url("https://x.supabase.co") == "https://x.supabase.co/functions/v1/ingest-run"


def test_function_url_strips_trailing_slash() -> None:
    assert _function_url("https://x.supabase.co/") == "https://x.supabase.co/functions/v1/ingest-run"


def test_function_url_passes_through_full_function_url() -> None:
    full = "https://x.supabase.co/functions/v1/ingest-run"
    assert _function_url(full) == full


# --- main() end-to-end --------------------------------------------------------


def _write_run(cerebrum_dir: Path, run_id: str, started_at: str) -> None:
    run_dir = cerebrum_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "mutants.jsonl").write_text(
        json.dumps(
            {
                "file": "a.py",
                "line": 1,
                "status": "SURVIVED",
                "mutation_type": "logic",
                "severity": "high",
                "rationale": "r",
                "diff": "d",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "coverage.json").write_text(
        json.dumps(
            [
                {
                    "file": "a.py",
                    "covered_lines": 5,
                    "instrumented_lines": 6,
                    "coverage_pct": 0.83,
                    "survivor_count": 1,
                    "max_severity": "high",
                }
            ]
        ),
        encoding="utf-8",
    )


def test_main_happy_path_pushes_newest_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cerebrum_dir = tmp_path / ".cerebrum"
    cerebrum_dir.mkdir()
    _make_db(cerebrum_dir / "history.sqlite", _ALL_COLUMNS, [_row("run-1", "2026-01-01T00:00:00Z")])
    _write_run(cerebrum_dir, "run-1", "2026-01-01T00:00:00Z")

    monkeypatch.setenv("CEREBRUM_CLOUD_URL", "https://x.supabase.co")
    monkeypatch.setenv("CEREBRUM_CLOUD_TOKEN", "tok")
    monkeypatch.setattr(
        "cerebrum_cloud_push.push.urllib.request.urlopen",
        lambda req: _FakeResponse({"survivors": 1, "run_files": 1, "run_uuid": "uuid-1"}),
    )

    code = main(["--cerebrum-dir", str(cerebrum_dir)])

    assert code == 0
    out = capsys.readouterr().out
    assert "pushed run run-1" in out
    assert "uuid-1" in out


def test_main_all_continues_past_failure_and_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cerebrum_dir = tmp_path / ".cerebrum"
    cerebrum_dir.mkdir()
    _make_db(
        cerebrum_dir / "history.sqlite",
        _ALL_COLUMNS,
        [_row("run-1", "2026-01-01T00:00:00Z"), _row("run-2", "2026-01-02T00:00:00Z")],
    )
    _write_run(cerebrum_dir, "run-1", "2026-01-01T00:00:00Z")
    _write_run(cerebrum_dir, "run-2", "2026-01-02T00:00:00Z")

    monkeypatch.setenv("CEREBRUM_CLOUD_URL", "https://x.supabase.co")
    monkeypatch.setenv("CEREBRUM_CLOUD_TOKEN", "tok")

    calls = {"n": 0}

    def fake_urlopen(req: object) -> _FakeResponse:
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("boom")
        return _FakeResponse({"survivors": 0, "run_files": 0, "run_uuid": "uuid-2"})

    monkeypatch.setattr("cerebrum_cloud_push.push.urllib.request.urlopen", fake_urlopen)

    code = main(["--cerebrum-dir", str(cerebrum_dir), "--all"])

    assert code == 1
    captured = capsys.readouterr()
    assert "FAILED run-1" in captured.err
    assert "pushed run run-2" in captured.out
    assert "1 pushed, 1 failed, 2 total" in captured.out


def test_main_rejects_all_and_run_id_together(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CEREBRUM_CLOUD_URL", "https://x.supabase.co")
    monkeypatch.setenv("CEREBRUM_CLOUD_TOKEN", "tok")

    with pytest.raises(SystemExit) as exc_info:
        main(["--all", "--run-id", "run-1"])

    assert exc_info.value.code == 1
    assert "mutually exclusive" in capsys.readouterr().err


def test_main_requires_url_and_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CEREBRUM_CLOUD_URL", raising=False)
    monkeypatch.delenv("CEREBRUM_CLOUD_TOKEN", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main([])

    assert exc_info.value.code == 1
    assert "must both be set" in capsys.readouterr().err
