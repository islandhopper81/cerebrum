"""Persist mutant records as JSON Lines under ``.cerebrum/mutants.jsonl``.

One record per line, appended, so a run streams results and REPORTING (#6) can
read them back without loading a whole run into memory.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from cerebrum.execute.models import MutantRecord

RECORDS_DIRNAME = ".cerebrum"
RECORDS_FILENAME = "mutants.jsonl"


def append_record(repo_root: Path, record: MutantRecord) -> Path:
    out_dir = repo_root / RECORDS_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / RECORDS_FILENAME
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record)) + "\n")
    return path
