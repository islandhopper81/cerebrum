"""Baseline stage: install, run the suite, enforce require-green, capture coverage.

``test`` is the canonical suite command: it always runs, gates ``require_green``,
provides the recorded duration (the per-mutant timeout basis used by EXECUTE
#4), and is the exact command re-run per mutant. ``coverage`` is an optional,
once-at-baseline command that only produces the coverage artifact when the fast
``test`` command does not emit one itself; its duration is never used.
"""

from __future__ import annotations

import warnings
from pathlib import Path

from cerebrum.baseline.coverage import CoverageData, parse_coverage
from cerebrum.baseline.models import BaselineResult
from cerebrum.config.model import Baseline, Module, Runtime
from cerebrum.exec.command import CommandResult, run_command


class BaselineError(Exception):
    """Raised when the baseline cannot be established — a failed install, a red
    suite under ``require_green``, or missing coverage output. Messages name the
    module and the problem so the failure is fixable without a traceback."""


class NoCoverageConfiguredWarning(UserWarning):
    """Emitted when a module declares no coverage output to capture."""


def run_baseline(
    module: Module,
    repo_root: Path,
    baseline_cfg: Baseline,
    runtime_cfg: Runtime,
) -> BaselineResult:
    module_dir = repo_root / module.root

    install_result = run_command(module.install, cwd=module_dir)
    if install_result.exit_code != 0:
        raise BaselineError(
            f"module '{module.name}': install command failed "
            f"(exit {install_result.exit_code}): {module.install}\n"
            f"{_stderr_tail(install_result)}"
        )

    test_result = run_command(module.test, cwd=module_dir)
    passed = test_result.exit_code == 0
    if not passed:
        message = (
            f"module '{module.name}': test suite is not green "
            f"(exit {test_result.exit_code}): {module.test}\n"
            f"{_stderr_tail(test_result)}"
        )
        if baseline_cfg.require_green:
            raise BaselineError(message)
        warnings.warn(message, stacklevel=2)

    if module.coverage is not None:
        run_command(module.coverage, cwd=module_dir)

    coverage = _capture_coverage(module, module_dir, repo_root)

    return BaselineResult(
        module_name=module.name,
        passed=passed,
        test_duration_seconds=test_result.duration_seconds,
        covered_lines=coverage.covered,
        instrumented_lines=coverage.instrumented,
        install_result=install_result,
        test_result=test_result,
    )


def _capture_coverage(module: Module, module_dir: Path, repo_root: Path) -> CoverageData:
    coverage_format = module.coverage_format
    coverage_path = module.coverage_path
    if coverage_format is None or coverage_path is None:
        warnings.warn(
            f"module '{module.name}': no coverage configured; "
            "covered-line map will be empty",
            NoCoverageConfiguredWarning,
            stacklevel=2,
        )
        return CoverageData(covered={}, instrumented={})

    coverage_file = module_dir / coverage_path
    if not coverage_file.exists():
        raise BaselineError(
            f"module '{module.name}': coverage file not found at {coverage_file} "
            f"after running the suite (expected format: {coverage_format})"
        )
    return parse_coverage(coverage_format, coverage_file, module_dir, repo_root)


def _stderr_tail(result: CommandResult, lines: int = 15) -> str:
    return "\n".join(result.stderr.strip().splitlines()[-lines:])
