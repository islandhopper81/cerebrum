"""The single-mutant lifecycle: the heart of Cerebrum.

Take one target, generate one mutant, apply it in an isolated worktree, gate it,
run the module's suite, and classify the outcome — one mutant at a time so a test
failure is attributable to exactly this mutation. The worktree is discarded on
exit, which is the revert. A target that is not covered short-circuits to
``NO_COVERAGE`` without any worktree; a proposal the operator declines or the gate
rejects raises :class:`NoMutantProduced` (a non-fatal skip, not a scored mutant).
"""

from __future__ import annotations

from pathlib import Path

from cerebrum.baseline.models import BaselineResult
from cerebrum.config.model import Module, Runtime
from cerebrum.exec import git
from cerebrum.exec.command import TIMEOUT_EXIT_CODE, CommandResult, run_command
from cerebrum.execute import gate
from cerebrum.execute.models import MutantRecord, MutantStatus
from cerebrum.execute.worktree import mutation_worktree
from cerebrum.generate.operator import MutantProposal, MutationOperator, MutationTarget


class NoMutantProduced(Exception):
    """Raised when no scorable mutant results — the operator returned nothing or
    the validity gate discarded the proposal."""


def run_mutant(
    module: Module,
    repo_root: Path,
    baseline: BaselineResult,
    runtime: Runtime,
    operator: MutationOperator,
    target: MutationTarget,
) -> MutantRecord:
    abs_path = (repo_root.resolve() / target.file).resolve()
    if target.line not in baseline.covered_lines.get(abs_path, set()):
        return MutantRecord(
            file=str(target.file),
            line=target.line,
            diff="",
            mutation_type="",
            status="NO_COVERAGE",
            covering_tests=module.test,
            rationale="",
            duration_seconds=0.0,
        )

    proposal = operator.propose(target)
    if proposal is None:
        raise NoMutantProduced(
            f"operator produced no mutant for {target.file}:{target.line}"
        )

    timeout = baseline.test_duration_seconds * runtime.test_timeout_multiplier

    with mutation_worktree(repo_root, module) as worktree_root:
        outcome = gate.evaluate(worktree_root, proposal, target)
        if outcome == "PATCH_INVALID":
            return _record(module, target, proposal, "BUILD_ERROR", 0.0)
        if outcome != "OK":
            raise NoMutantProduced(
                f"mutant rejected by validity gate ({outcome}) "
                f"for {target.file}:{target.line}"
            )

        git.apply(worktree_root, proposal.diff)
        test_result = run_command(
            module.test, cwd=worktree_root / module.root, timeout=timeout
        )
        return _record(
            module, target, proposal, _classify(test_result), test_result.duration_seconds
        )


def _classify(result: CommandResult) -> MutantStatus:
    if result.exit_code == TIMEOUT_EXIT_CODE:
        return "TIMEOUT"
    if result.exit_code != 0:
        return "KILLED"
    return "SURVIVED"


def _record(
    module: Module,
    target: MutationTarget,
    proposal: MutantProposal,
    status: MutantStatus,
    duration_seconds: float,
) -> MutantRecord:
    return MutantRecord(
        file=str(target.file),
        line=target.line,
        diff=proposal.diff,
        mutation_type=proposal.mutation_type,
        status=status,
        covering_tests=module.test,
        rationale=proposal.rationale,
        duration_seconds=duration_seconds,
    )
