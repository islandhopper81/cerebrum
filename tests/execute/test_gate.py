"""Unit tests for the validity gate."""

from __future__ import annotations

from pathlib import Path

from cerebrum.execute import gate
from cerebrum.generate.operator import MutantProposal, MutationTarget
from tests.support import init_git_repo, make_patch


def _target(language: str = "python") -> MutationTarget:
    return MutationTarget(
        file=Path("a.py"), line=1, source_text="", language=language
    )


def _proposal(diff: str, *, equivalent: bool = False) -> MutantProposal:
    return MutantProposal(
        diff=diff, mutation_type="logic", rationale="", equivalent=equivalent
    )


def test_equivalent_flag_is_rejected(tmp_path: Path) -> None:
    proposal = _proposal("--- a/a.py\n+++ b/a.py\n@@\n-a=1\n+a=2\n", equivalent=True)
    assert gate.evaluate(tmp_path, proposal, _target()) == "EQUIVALENT_DECLARED"


def test_comment_only_change_has_no_behavior_change(tmp_path: Path) -> None:
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-# old comment\n+# new comment\n"
    assert gate.evaluate(tmp_path, _proposal(diff), _target()) == "NO_BEHAVIOR_CHANGE"


def test_whitespace_only_change_has_no_behavior_change(tmp_path: Path) -> None:
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 1\n+x   =   1\n"
    assert gate.evaluate(tmp_path, _proposal(diff), _target()) == "NO_BEHAVIOR_CHANGE"


def test_real_change_that_applies_is_ok(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.py": "x = 1\n"})
    diff = make_patch("a.py", "x = 1\n", "x = 2\n")
    assert gate.evaluate(tmp_path, _proposal(diff), _target()) == "OK"


def test_real_change_that_does_not_apply_is_patch_invalid(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.py": "x = 1\n"})
    diff = make_patch("a.py", "y = 9\n", "y = 2\n")
    assert gate.evaluate(tmp_path, _proposal(diff), _target()) == "PATCH_INVALID"
