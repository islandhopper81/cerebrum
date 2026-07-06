"""Validity gate: reject a proposed mutant before spending a test run on it.

Three rejections, cheapest first: the operator's own ``equivalent`` flag, a
heuristic behaviour-change check (a change that is only whitespace or comments
cannot be caught by a test, so it is noise), and finally ``git apply --check``.
Per the #3 scope there is no build/lint command — ``BUILD_ERROR`` comes only from
a patch that will not apply. The behaviour-change check is a heuristic: it may let
a truly equivalent mutant through (surfacing later as ``SURVIVED`` noise) but will
not reject a genuine change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from cerebrum.exec import git
from cerebrum.generate.operator import MutantProposal, MutationTarget

GateOutcome = Literal["OK", "PATCH_INVALID", "EQUIVALENT_DECLARED", "NO_BEHAVIOR_CHANGE"]

_COMMENT_PREFIX = {
    "javascript": "//",
    "typescript": "//",
    "js": "//",
    "ts": "//",
    "java": "//",
    "go": "//",
    "c": "//",
    "cpp": "//",
    "rust": "//",
    "python": "#",
    "py": "#",
    "ruby": "#",
    "shell": "#",
}


def evaluate(
    worktree_root: Path, proposal: MutantProposal, target: MutationTarget
) -> GateOutcome:
    if proposal.equivalent:
        return "EQUIVALENT_DECLARED"
    if not _has_behavior_change(proposal.diff, target.language):
        return "NO_BEHAVIOR_CHANGE"
    if not git.apply_check(worktree_root, proposal.diff):
        return "PATCH_INVALID"
    return "OK"


def _has_behavior_change(diff: str, language: str) -> bool:
    prefix = _COMMENT_PREFIX.get(language.lower())
    added: list[str] = []
    removed: list[str] = []
    for raw in diff.splitlines():
        if raw.startswith(("+++", "---")):
            continue
        if raw.startswith("+"):
            _collect(raw[1:], prefix, added)
        elif raw.startswith("-"):
            _collect(raw[1:], prefix, removed)
    return sorted(added) != sorted(removed)


def _collect(content: str, prefix: str | None, into: list[str]) -> None:
    stripped = content.strip()
    if not stripped:
        return
    if prefix is not None and stripped.startswith(prefix):
        return
    into.append("".join(content.split()))
