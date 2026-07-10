"""Push one or more Cerebrum runs' results to Cerebrum Cloud.

Reads the local ``.cerebrum/`` artifacts that ``cerebrum run`` already writes
and POSTs them to the ``ingest-run`` Edge Function. Stdlib only, so it needs no
extra dependencies beyond this package itself.

Config comes from the environment:
  CEREBRUM_CLOUD_URL    Base URL of the Supabase project
                        (e.g. https://<ref>.supabase.co) OR the full function
                        URL (.../functions/v1/ingest-run) -- either is accepted.
  CEREBRUM_CLOUD_TOKEN  The per-project ingest token (shown once when created
                        in the dashboard).

Usage:
  cerebrum-cloud-push                 # newest run in .cerebrum/history.sqlite
  cerebrum-cloud-push --run-id <id>   # a specific run
  cerebrum-cloud-push --all           # every run in history.sqlite, oldest first
  cerebrum-cloud-push --cerebrum-dir path/to/.cerebrum
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import NoReturn

_RUN_COLUMNS = [
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


class PushError(Exception):
    """A single run failed to push; caller decides whether to abort or continue."""


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        _fail(f"no history db at {db_path} -- has `cerebrum run` been run here?")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _available_columns(conn: sqlite3.Connection) -> list[str]:
    """Columns from _RUN_COLUMNS actually present in this DB's runs table,
    preserving order. Older history.sqlite files (pre coverage-persistence
    engine change) lack covered_lines/instrumented_lines/coverage_pct; those
    are simply omitted from the SELECT and filled in as None below, so both
    schema versions push cleanly."""
    present = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
    return [c for c in _RUN_COLUMNS if c in present]


def _list_run_ids(db_path: Path) -> list[str]:
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT run_id FROM runs ORDER BY started_at ASC").fetchall()
    except sqlite3.OperationalError as exc:
        _fail(f"could not read runs table ({exc}).")
    finally:
        conn.close()
    return [row["run_id"] for row in rows]


def _load_run(db_path: Path, run_id: str | None) -> dict[str, object]:
    conn = _connect(db_path)
    try:
        cols = _available_columns(conn)
        col_list = ", ".join(cols)
        if run_id is None:
            row = conn.execute(
                f"SELECT {col_list} FROM runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute(
                f"SELECT {col_list} FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
    except sqlite3.OperationalError as exc:
        _fail(f"could not read runs table ({exc}).")
    finally:
        conn.close()
    if row is None:
        _fail(f"no run found ({'latest' if run_id is None else run_id}) in {db_path}")
    return {key: (row[key] if key in row.keys() else None) for key in _RUN_COLUMNS}


def _load_survivors(run_dir: Path) -> list[dict[str, object]]:
    path = run_dir / "mutants.jsonl"
    if not path.exists():
        return []
    survivors: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("status") != "SURVIVED":
            continue
        survivors.append(
            {
                "file": rec["file"],
                "line": rec["line"],
                "mutation_type": rec.get("mutation_type", ""),
                "severity": rec.get("severity", ""),
                "rationale": rec.get("rationale", ""),
                "diff": rec.get("diff"),
                "covering_tests": rec.get("covering_tests"),
                "suggested_test": rec.get("suggested_test"),
            }
        )
    return survivors


def _load_run_files(run_dir: Path) -> list[dict[str, object]]:
    path = run_dir / "coverage.json"
    if not path.exists():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")))


def _function_url(raw: str) -> str:
    base = raw.rstrip("/")
    if base.endswith("/ingest-run"):
        return base
    return f"{base}/functions/v1/ingest-run"


def _post(url: str, token: str, payload: dict[str, object]) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result: dict[str, object] = json.loads(resp.read().decode("utf-8"))
            return result
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise PushError(f"ingest failed (HTTP {exc.code}): {body}") from exc
    except urllib.error.URLError as exc:
        raise PushError(f"could not reach {url}: {exc.reason}") from exc


def _fail(message: str) -> NoReturn:
    print(f"cerebrum-cloud-push: {message}", file=sys.stderr)
    raise SystemExit(1)


def _push_one(cerebrum_dir: Path, run_id: str, url: str, token: str) -> str:
    """Push a single run. Returns a one-line summary. Raises PushError on failure."""
    run = _load_run(cerebrum_dir / "history.sqlite", run_id)
    run_dir = cerebrum_dir / "runs" / run_id
    payload: dict[str, object] = {
        "run": run,
        "survivors": _load_survivors(run_dir),
        "run_files": _load_run_files(run_dir),
    }
    result = _post(_function_url(url), token, payload)
    return (
        f"pushed run {run_id} ({run['module']}, {run['started_at']}): "
        f"{result.get('survivors', 0)} survivor(s), "
        f"{result.get('run_files', 0)} file(s) "
        f"(run_uuid {result.get('run_uuid', '?')})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Push Cerebrum run(s) to Cerebrum Cloud.")
    parser.add_argument(
        "--cerebrum-dir",
        default=".cerebrum",
        help="Path to the .cerebrum directory (default: .cerebrum).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run id to push (default: the most recent run by started_at).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Push every run in history.sqlite, oldest first (backfill). "
        "Mutually exclusive with --run-id. Continues past individual "
        "failures and reports a summary at the end.",
    )
    args = parser.parse_args(argv)

    if args.all and args.run_id:
        _fail("--all and --run-id are mutually exclusive.")

    url_env = os.environ.get("CEREBRUM_CLOUD_URL")
    token = os.environ.get("CEREBRUM_CLOUD_TOKEN")
    if not url_env or not token:
        _fail("CEREBRUM_CLOUD_URL and CEREBRUM_CLOUD_TOKEN must both be set.")

    cerebrum_dir = Path(args.cerebrum_dir)

    if not args.all:
        run = _load_run(cerebrum_dir / "history.sqlite", args.run_id)
        try:
            print(_push_one(cerebrum_dir, str(run["run_id"]), url_env, token))
        except PushError as exc:
            _fail(str(exc))
        return 0

    run_ids = _list_run_ids(cerebrum_dir / "history.sqlite")
    if not run_ids:
        _fail(f"no runs found in {cerebrum_dir / 'history.sqlite'}")

    ok, failed = 0, 0
    for run_id in run_ids:
        try:
            print(_push_one(cerebrum_dir, run_id, url_env, token))
            ok += 1
        except PushError as exc:
            print(f"cerebrum-cloud-push: FAILED {run_id}: {exc}", file=sys.stderr)
            failed += 1

    print(f"backfill complete: {ok} pushed, {failed} failed, {len(run_ids)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
