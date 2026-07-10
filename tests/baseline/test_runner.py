"""Unit tests for the baseline stage runner."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from cerebrum.baseline.runner import BaselineError, run_baseline
from cerebrum.config.model import Baseline, Module, Runtime

_WINDOWS = os.name == "nt"


def _fail_cmd() -> str:
    return "exit 3"


def _module(**overrides: Any) -> Module:
    defaults: dict[str, Any] = {
        "name": "backend",
        "root": "backend",
        "language": "javascript",
        "install": "echo installing",
        "test": "echo testing",
        "source": ["routes/**/*.js"],
        "coverage_format": "lcov",
        "coverage_path": "coverage/lcov.info",
    }
    defaults.update(overrides)
    return Module(**defaults)


def _prepare(tmp_path: Path, with_coverage: bool = True) -> Path:
    module_dir = tmp_path / "backend"
    source = module_dir / "routes" / "meals.js"
    source.parent.mkdir(parents=True)
    source.write_text("// x\n", encoding="utf-8")
    if with_coverage:
        cov = module_dir / "coverage" / "lcov.info"
        cov.parent.mkdir(parents=True)
        cov.write_text(
            "SF:routes/meals.js\nDA:1,5\nDA:2,0\nend_of_record\n",
            encoding="utf-8",
        )
    return tmp_path


def test_green_baseline(tmp_path: Path) -> None:
    repo_root = _prepare(tmp_path)
    result = run_baseline(_module(), repo_root, Baseline(), Runtime())
    assert result.passed
    assert result.test_duration_seconds > 0
    assert result.covered_lines
    assert result.instrumented_lines
    assert result.test_result.command == "echo testing"


def test_red_test_requires_green_raises(tmp_path: Path) -> None:
    repo_root = _prepare(tmp_path)
    module = _module(test=_fail_cmd())
    with pytest.raises(BaselineError, match="not green"):
        run_baseline(module, repo_root, Baseline(require_green=True), Runtime())


def test_red_test_without_require_green_warns(tmp_path: Path) -> None:
    repo_root = _prepare(tmp_path)
    module = _module(test=_fail_cmd())
    with pytest.warns(UserWarning):
        result = run_baseline(module, repo_root, Baseline(require_green=False), Runtime())
    assert result.passed is False
    assert result.covered_lines


def test_install_failure_always_raises(tmp_path: Path) -> None:
    repo_root = _prepare(tmp_path)
    module = _module(install=_fail_cmd())
    with pytest.raises(BaselineError, match="install"):
        run_baseline(module, repo_root, Baseline(require_green=False), Runtime())


def test_missing_coverage_file_raises(tmp_path: Path) -> None:
    repo_root = _prepare(tmp_path, with_coverage=False)
    with pytest.raises(BaselineError, match="coverage file not found"):
        run_baseline(_module(), repo_root, Baseline(), Runtime())


def test_coverage_command_invoked_and_duration_from_test(tmp_path: Path) -> None:
    repo_root = _prepare(tmp_path)
    module = _module(coverage="echo ran > cov-ran.txt")
    result = run_baseline(module, repo_root, Baseline(), Runtime())
    assert (tmp_path / "backend" / "cov-ran.txt").exists()
    assert result.test_result.command == "echo testing"
