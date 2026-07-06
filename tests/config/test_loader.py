"""File-level loading: parsing, error wrapping, and message quality."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from cerebrum.config.loader import ConfigError, load_config

WriteConfig = Callable[..., Path]


def test_load_valid_config(write_config: WriteConfig, config_dict: dict[str, Any]) -> None:
    path = write_config(config_dict)
    config = load_config(path)
    assert config.project == "Demo"
    assert config.modules[0].name == "backend"


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_empty_file_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "cerebrum.yaml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="empty"):
        load_config(path)


def test_non_mapping_top_level_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "cerebrum.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(path)


def test_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "cerebrum.yaml"
    path.write_text("version: 1\n  bad: : indent\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(path)


def test_validation_error_names_field_and_file(
    write_config: WriteConfig, config_dict: dict[str, Any]
) -> None:
    config_dict["modules"][0]["coverage_format"] = "lcov"
    path = write_config(config_dict)
    with pytest.raises(ConfigError) as exc_info:
        load_config(path)
    message = str(exc_info.value)
    assert str(path) in message
    assert "coverage_path" in message
