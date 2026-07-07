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

from cerebrum.execute.models import MutantRecord

RECORDS_DIRNAME = ".cerebrum"
RECORDS_FILENAME = "mutants.jsonl"
RUNS_DIRNAME = "runs"


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


def load_records(repo_root: Path, run_id: str) -> list[MutantRecord]:
    """Read back every record persisted for ``run_id`` by :func:`append_record`."""
    path = repo_root / RECORDS_DIRNAME / RUNS_DIRNAME / run_id / RECORDS_FILENAME
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        records.append(MutantRecord(**json.loads(line)))
    return records
