"""CLI `cerebrum validate` behavior."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from cerebrum.cli import main

WriteConfig = Callable[..., Path]

EXAMPLE_CONFIG = Path(__file__).resolve().parents[2] / "examples" / "feedthefamily.cerebrum.yaml"


def test_validate_exit_zero_with_source_count(
    write_config: WriteConfig,
    config_dict: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = write_config(config_dict)
    backend = path.parent / "backend"
    backend.mkdir()
    (backend / "server.js").write_text("//", encoding="utf-8")

    exit_code = main(["validate", "-c", str(path)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "backend [javascript]: 1 source files" in out
    assert "Valid." in out


def test_validate_exit_one_on_broken_config(
    write_config: WriteConfig,
    config_dict: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_dict["modules"][0]["coverage_path"] = "coverage/lcov.info"  # missing format
    path = write_config(config_dict)

    exit_code = main(["validate", "-c", str(path)])
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "coverage_format" in err


def test_committed_feedthefamily_sample_validates(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["validate", "-c", str(EXAMPLE_CONFIG)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "project: FeedTheFamily" in out


def test_validate_zero_match_module_still_valid_ascii_only(
    write_config: WriteConfig,
    config_dict: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # No source files exist under the module root: this must warn (not crash) and
    # stay valid. Output must be ASCII-only so it prints on a cp1252 console.
    path = write_config(config_dict)

    exit_code = main(["validate", "-c", str(path)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "0 source files" in out
    assert "warning: no source files matched" in out
    out.encode("cp1252")  # would raise UnicodeEncodeError on non-ASCII output
