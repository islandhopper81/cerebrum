"""Importable test helpers (kept out of conftest so tests can import them directly)."""

from __future__ import annotations

import difflib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cerebrum.baseline.models import BaselineResult, CoveredLineMap
from cerebrum.config.model import Module
from cerebrum.exec.command import CommandResult
from cerebrum.generate.operator import MutantProposal, MutationTarget


def base_config() -> dict[str, Any]:
    """A minimal, valid config mapping. Tests deep-copy and mutate this."""
    return {
        "version": 1,
        "project": "Demo",
        "modules": [
            {
                "name": "backend",
                "root": "backend",
                "language": "javascript",
                "install": "npm ci",
                "test": "npm test",
                "source": ["**/*.js"],
            }
        ],
        "mutation": {"model": "claude-sonnet-5", "budget_usd": 10},
    }


@dataclass
class FakeOperator:
    """Deterministic stand-in for the Claude operator. Records the targets it was
    asked about so lifecycle tests can assert short-circuits (e.g. NO_COVERAGE)."""

    proposal: MutantProposal | None
    calls: list[MutationTarget] | None = None

    def propose(self, target: MutationTarget) -> MutantProposal | None:
        if self.calls is None:
            self.calls = []
        self.calls.append(target)
        return self.proposal


def make_patch(rel_path: str, old_text: str, new_text: str) -> str:
    """Build a git-appliable unified diff (``a/`` ``b/`` prefixes) between two
    versions of ``rel_path``. Both texts should end with a newline."""
    old = old_text.splitlines(keepends=True)
    new = new_text.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(old, new, fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}")
    )


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)


def init_git_repo(root: Path, files: dict[str, str]) -> None:
    """Initialise a committed git repo at ``root`` containing ``files``."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Cerebrum Test")
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")


def make_module(**overrides: Any) -> Module:
    defaults: dict[str, Any] = {
        "name": "app",
        "root": ".",
        "language": "python",
        "install": "echo installing",
        "test": "echo testing",
        "source": ["**/*.py"],
    }
    defaults.update(overrides)
    return Module(**defaults)


def _cmd_result() -> CommandResult:
    return CommandResult(
        command="echo", exit_code=0, stdout="", stderr="", duration_seconds=0.01
    )


def make_baseline(
    covered_lines: CoveredLineMap,
    *,
    test_duration_seconds: float = 2.0,
    module_name: str = "app",
) -> BaselineResult:
    return BaselineResult(
        module_name=module_name,
        passed=True,
        test_duration_seconds=test_duration_seconds,
        covered_lines=covered_lines,
        instrumented_lines={},
        install_result=_cmd_result(),
        test_result=_cmd_result(),
    )
