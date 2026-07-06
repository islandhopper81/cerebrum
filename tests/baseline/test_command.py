"""Unit tests for the shared shell command runner."""

from __future__ import annotations

import os
from pathlib import Path

from cerebrum.exec.command import TIMEOUT_EXIT_CODE, run_command

_WINDOWS = os.name == "nt"


def _fail_cmd() -> str:
    return "echo boom 1>&2 & exit 3" if _WINDOWS else "echo boom 1>&2; exit 3"


def _sleep_cmd(seconds: int) -> str:
    return f"ping 127.0.0.1 -n {seconds + 1} > NUL" if _WINDOWS else f"sleep {seconds}"


def test_run_command_success(tmp_path: Path) -> None:
    result = run_command("echo hi", cwd=tmp_path)
    assert result.exit_code == 0
    assert "hi" in result.stdout
    assert result.duration_seconds > 0


def test_run_command_captures_exit_and_stderr(tmp_path: Path) -> None:
    result = run_command(_fail_cmd(), cwd=tmp_path)
    assert result.exit_code == 3
    assert "boom" in result.stderr


def test_run_command_timeout_returns_sentinel(tmp_path: Path) -> None:
    result = run_command(_sleep_cmd(5), cwd=tmp_path, timeout=0.5)
    assert result.exit_code == TIMEOUT_EXIT_CODE
