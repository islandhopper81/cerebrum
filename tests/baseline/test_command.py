"""Unit tests for the shared shell command runner."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from cerebrum.exec.command import TIMEOUT_EXIT_CODE, run_command

_WINDOWS = os.name == "nt"


def _fail_cmd() -> str:
    return "echo boom 1>&2 & exit 3" if _WINDOWS else "echo boom 1>&2; exit 3"


def _sleep_cmd(seconds: int) -> str:
    return f"ping 127.0.0.1 -n {seconds + 1} > NUL" if _WINDOWS else f"sleep {seconds}"


def _invalid_utf8_cmd(tmp_path: Path) -> str:
    """A command whose stdout contains a byte (0x8f) that is invalid both as a
    standalone UTF-8 byte and in the Windows cp1252 codepage — real npm/jest
    output can include bytes like this."""
    script = tmp_path / "_emit_invalid_utf8.py"
    script.write_text(
        "import sys\nsys.stdout.buffer.write(bytes([0x41, 0x8F, 0x42]))\n",
        encoding="utf-8",
    )
    return f'"{sys.executable}" "{script}"'


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


def test_run_command_survives_invalid_utf8_output(tmp_path: Path) -> None:
    result = run_command(_invalid_utf8_cmd(tmp_path), cwd=tmp_path)
    assert result.exit_code == 0
    assert "A" in result.stdout and "B" in result.stdout
