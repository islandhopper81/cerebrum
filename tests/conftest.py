"""Shared fixtures and helpers for the config test suite."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.support import base_config


@pytest.fixture
def config_dict() -> dict[str, Any]:
    return copy.deepcopy(base_config())


@pytest.fixture
def write_config(tmp_path: Path):
    """Return a helper that writes a config mapping to ``cerebrum.yaml``."""

    def _write(data: dict[str, Any], name: str = "cerebrum.yaml") -> Path:
        path = tmp_path / name
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return path

    return _write
