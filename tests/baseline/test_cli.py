"""Integration tests for the `cerebrum baseline` CLI subcommand."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from cerebrum.cli import main


def _write_project(tmp_path: Path, test: str = "echo testing") -> Path:
    module_dir = tmp_path / "backend"
    source = module_dir / "routes" / "meals.js"
    source.parent.mkdir(parents=True)
    source.write_text("// x\n", encoding="utf-8")
    cov = module_dir / "coverage" / "lcov.info"
    cov.parent.mkdir(parents=True)
    cov.write_text("SF:routes/meals.js\nDA:1,5\nDA:2,0\nend_of_record\n", encoding="utf-8")

    config: dict[str, Any] = {
        "version": 1,
        "project": "Demo",
        "modules": [
            {
                "name": "backend",
                "root": "backend",
                "language": "javascript",
                "install": "echo installing",
                "test": test,
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


def test_baseline_cli_green(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_project(tmp_path)
    code = main(["baseline", "-c", str(path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "backend" in out
    assert "green" in out


def test_baseline_cli_red(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_project(tmp_path, test="exit 3")
    code = main(["baseline", "-c", str(path)])
    assert code == 1
