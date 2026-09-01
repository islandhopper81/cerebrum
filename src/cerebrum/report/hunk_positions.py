"""Diagnostic: detect hunk-header positioning mismatches among ``BUILD_ERROR`` mutants.

A distinct failure mode from the hunk-*count* mismatches ``git apply --recount`` fixes
(see #29): a diff hunk whose header is internally consistent but whose claimed starting
line doesn't match where its cited context actually appears in the target file. Pure —
the only I/O is reading each flagged record's own target file, mirroring
:mod:`cerebrum.report.survivors`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from cerebrum.execute.models import MutantRecord

_OLD_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")


@dataclass(frozen=True)
class PositionMismatch:
    file: str
    claimed_line: int
    actual_line: int | None  # None if the cited context wasn't found anywhere in the file
    diff: str


def find_position_mismatches(
    records: list[MutantRecord], repo_root: Path
) -> list[PositionMismatch]:
    mismatches: list[PositionMismatch] = []
    for record in records:
        if record.status != "BUILD_ERROR":
            continue
        mismatch = _check_record(record, repo_root)
        if mismatch is not None:
            mismatches.append(mismatch)
    return mismatches


def _check_record(record: MutantRecord, repo_root: Path) -> PositionMismatch | None:
    claimed_line = None
    old_side: list[str] = []
    for line in record.diff.splitlines():
        header_match = _OLD_HUNK_HEADER.match(line)
        if header_match is not None:
            claimed_line = int(header_match.group(1))
            continue
        if claimed_line is None:
            continue
        if line.startswith((" ", "-")):
            old_side.append(line[1:])

    if claimed_line is None or not old_side:
        return None

    target = repo_root / record.file
    if not target.is_file():
        return None

    file_lines = target.read_text(encoding="utf-8").splitlines()
    actual_line = _find_sequence(file_lines, old_side)

    if actual_line == claimed_line:
        return None
    return PositionMismatch(
        file=record.file,
        claimed_line=claimed_line,
        actual_line=actual_line,
        diff=record.diff,
    )


def _find_sequence(file_lines: list[str], sequence: list[str]) -> int | None:
    span = len(sequence)
    for start in range(len(file_lines) - span + 1):
        if file_lines[start : start + span] == sequence:
            return start + 1  # 1-indexed
    return None
