"""Parallel single-mutant driver: run many targets across a pool of
pre-installed, reused worktrees.

Reuses #3's gate/apply/test/classify core (``lifecycle.run_mutant_in_worktree``)
per target, dispatched across up to ``runtime.parallelism`` worker threads
against a :class:`~cerebrum.execute.pool.WorktreePool` sized to the smaller of
``parallelism`` and the target count — installing once per worktree instead of
once per mutant. Results are collected via ``as_completed`` in the submitting
thread, so persistence (``append_record``) and the returned list are built up
serially with no extra locking; record order therefore reflects completion
order, not ``targets``' input order.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from cerebrum.baseline.models import BaselineResult
from cerebrum.config.model import Module, Runtime
from cerebrum.execute.lifecycle import (
    NoMutantProduced,
    is_covered,
    no_coverage_record,
    propose_mutant,
    run_mutant_in_worktree,
)
from cerebrum.execute.models import MutantRecord
from cerebrum.execute.pool import WorktreePool
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
    if not targets:
        return []

    size = min(runtime.parallelism, len(targets))

    def _run_one(target: MutationTarget, pool: WorktreePool) -> MutantRecord | None:
        if not is_covered(baseline, repo_root, target):
            return no_coverage_record(module, target)
        try:
            proposal = propose_mutant(operator, target)
            with pool.lease() as worktree_root:
                return run_mutant_in_worktree(
                    module, worktree_root, baseline, runtime, target, proposal
                )
        except NoMutantProduced:
            return None

    records: list[MutantRecord] = []
    with WorktreePool(repo_root, module, size) as pool:
        with ThreadPoolExecutor(max_workers=size) as executor:
            futures = [executor.submit(_run_one, target, pool) for target in targets]
            for future in as_completed(futures):
                record = future.result()
                if record is None:
                    continue
                append_record(repo_root, record)
                records.append(record)
    return records
