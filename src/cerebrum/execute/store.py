"""Persist mutant records as JSON Lines.

One record per line, appended, so a run streams results without loading a whole
run into memory. ``cerebrum mutate`` (an ad-hoc single mutation, no ``run_id``)
writes to the legacy flat ``.cerebrum/mutants.jsonl``. ``cerebrum run`` (a "run"
in the trend sense, #6) passes its ``run_id`` so records land under
``.cerebrum/runs/<run_id>/mutants.jsonl`` instead — one file per run, so
REPORTING can read back exactly one run's records without re-scanning history.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from cerebrum.execute.models import MutantRecord

RECORDS_DIRNAME = ".cerebrum"
RECORDS_FILENAME = "mutants.jsonl"
RUNS_DIRNAME = "runs"
COVERAGE_FILENAME = "coverage.json"

_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def append_record(repo_root: Path, record: MutantRecord, run_id: str | None = None) -> Path:
    base = repo_root / RECORDS_DIRNAME
    if run_id is None:
        out_dir = base
    else:
        out_dir = base / RUNS_DIRNAME / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / RECORDS_FILENAME
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record)) + "\n")
    return path


def _rel_posix(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def build_coverage_rows(
    covered_lines: dict[Path, set[int]],
    instrumented_lines: dict[Path, set[int]],
    records: list[MutantRecord],
    repo_root: Path,
) -> list[dict[str, Any]]:
    """Roll up per-file coverage joined with surviving-mutant counts.

    One row per instrumented file: covered/instrumented line counts, coverage
    fraction, and the count and worst severity of survivors on that file. File
    paths are repo-relative POSIX so they match ``MutantRecord.file`` and are
    portable across machines.
    """
    survivor_counts: dict[str, int] = {}
    survivor_worst: dict[str, int] = {}
    for record in records:
        if record.status != "SURVIVED":
            continue
        key = record.file.replace("\\", "/")
        survivor_counts[key] = survivor_counts.get(key, 0) + 1
        rank = _SEVERITY_RANK.get(record.severity)
        if rank is not None and rank > survivor_worst.get(key, 0):
            survivor_worst[key] = rank

    rank_to_severity = {v: k for k, v in _SEVERITY_RANK.items()}
    rows: list[dict[str, Any]] = []
    for path, instrumented in instrumented_lines.items():
        rel = _rel_posix(path, repo_root)
        instrumented_count = len(instrumented)
        covered_count = len(covered_lines.get(path, set()))
        worst_rank = survivor_worst.get(rel)
        rows.append(
            {
                "file": rel,
                "covered_lines": covered_count,
                "instrumented_lines": instrumented_count,
                "coverage_pct": (
                    covered_count / instrumented_count if instrumented_count else None
                ),
                "survivor_count": survivor_counts.get(rel, 0),
                "max_severity": rank_to_severity.get(worst_rank) if worst_rank else None,
            }
        )
    rows.sort(key=lambda r: r["file"])
    return rows


def write_coverage(repo_root: Path, run_id: str, rows: list[dict[str, Any]]) -> Path:
    """Write the per-file coverage rollup for ``run_id`` as JSON."""
    out_dir = repo_root / RECORDS_DIRNAME / RUNS_DIRNAME / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / COVERAGE_FILENAME
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return path


def load_records(repo_root: Path, run_id: str) -> list[MutantRecord]:
    """Read back every record persisted for ``run_id`` by :func:`append_record`."""
    path = repo_root / RECORDS_DIRNAME / RUNS_DIRNAME / run_id / RECORDS_FILENAME
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        records.append(MutantRecord(**json.loads(line)))
    return records
