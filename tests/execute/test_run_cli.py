"""CLI tests for the `cerebrum run` subcommand.

Covers only paths that never construct a real operator — targeting failures
and an empty target set — so no LLM call or API key is needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from cerebrum.cli import main


def _write_project(
    tmp_path: Path,
    *,
    strategy: str = "coverage",
    lcov: str = "SF:routes/meals.js\nDA:1,5\nDA:2,0\nend_of_record\n",
) -> Path:
    module_dir = tmp_path / "backend"
    source = module_dir / "routes" / "meals.js"
    source.parent.mkdir(parents=True)
    source.write_text("// x\n// y\n", encoding="utf-8")
    cov = module_dir / "coverage" / "lcov.info"
    cov.parent.mkdir(parents=True)
    cov.write_text(lcov, encoding="utf-8")

    config: dict[str, Any] = {
        "version": 1,
        "project": "Demo",
        "targeting": {"strategy": strategy},
        "modules": [
            {
                "name": "backend",
                "root": "backend",
                "language": "javascript",
                "install": "echo installing",
                "test": "echo testing",
                "coverage_format": "lcov",
                "coverage_path": "coverage/lcov.info",
                "source": ["routes/**/*.js"],
            }
        ],
        "mutation": {"model": "claude-sonnet-5", "budget_usd": 10},
    }
    path = tmp_path / "cerebrum.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def test_run_changed_strategy_without_diff_fails_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_project(tmp_path, strategy="changed")

    code = main(["run", "-c", str(path)])

    assert code == 1
    assert "--diff" in capsys.readouterr().err


def test_run_llm_risk_strategy_raises_targeting_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_project(tmp_path, strategy="llm-risk")

    code = main(["run", "-c", str(path)])

    assert code == 1
    assert "llm-risk" in capsys.readouterr().err


def test_run_with_no_covered_lines_reports_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_project(
        tmp_path, lcov="SF:routes/meals.js\nDA:1,0\nDA:2,0\nend_of_record\n"
    )

    code = main(["run", "-c", str(path)])

    assert code == 0
    assert "no targets to mutate" in capsys.readouterr().out
