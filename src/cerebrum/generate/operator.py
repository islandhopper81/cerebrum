"""The GENERATE seam: how a mutation operator hands the lifecycle one mutant.

This is a hard API imported by EXECUTE (#3), and later by TARGETING (#5). The
lifecycle depends only on :class:`MutationOperator` — the real Claude-backed
:class:`~cerebrum.generate.llm.LLMOperator` and test fakes are interchangeable
behind it, which is what keeps the lifecycle deterministically testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

MutationType = Literal[
    "conditional",
    "arithmetic",
    "boundary",
    "return-value",
    "exception",
    "logic",
    "other",
]


@dataclass(frozen=True)
class MutationTarget:
    """One place to mutate. ``file`` is repo-root-relative so it lines up with the
    diff paths and the persisted record; ``source_text`` is the file's full
    current content, given to the operator for context."""

    file: Path
    line: int
    source_text: str
    language: str


@dataclass(frozen=True)
class MutantProposal:
    """One mutant. ``diff`` is a unified diff addressing ``file`` by its
    repo-root-relative path (``a/… b/…``), appliable with ``git apply`` at a
    worktree root. ``equivalent`` is the operator's own signal that the mutant
    does not change behaviour and should be discarded."""

    diff: str
    mutation_type: MutationType
    rationale: str
    equivalent: bool = False


class MutationOperator(Protocol):
    """Produces at most one mutant for a target, or ``None`` if it cannot."""

    def propose(self, target: MutationTarget) -> MutantProposal | None: ...
