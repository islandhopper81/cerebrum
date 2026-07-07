"""Sequential single-mutant driver: run many targets one after another.

Reuses #3's ``run_mutant`` per target, streaming each scored record to disk as it
completes. This is the exact seam #4 replaces with a worktree pool and parallel
workers — the per-target semantics (skip a discarded proposal, abort the run on a
broken worktree) should carry over unchanged when that swap happens.
"""

from __future__ import annotations

from pathlib import Path

from cerebrum.baseline.models import BaselineResult
from cerebrum.config.model import Module, Runtime
from cerebrum.execute.lifecycle import NoMutantProduced, run_mutant
from cerebrum.execute.models import MutantRecord
from cerebrum.execute.store import append_record
from cerebrum.generate.operator import MutationOperator, MutationTarget


def run_targets(
    module: Module,
    repo_root: Path,
    baseline: BaselineResult,
    runtime: Runtime,
    operator: MutationOperator,
    targets: list[MutationTarget],
) -> list[MutantRecord]:
    records: list[MutantRecord] = []
    for target in targets:
        try:
            record = run_mutant(module, repo_root, baseline, runtime, operator, target)
        except NoMutantProduced:
            continue
        append_record(repo_root, record)
        records.append(record)
    return records
