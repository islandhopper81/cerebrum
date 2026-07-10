"""Model-level validation and glob resolution."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cerebrum.config.model import CerebrumConfig, Module, ZeroMatchWarning
from tests.support import base_config


def _build(**overrides: Any) -> CerebrumConfig:
    data = copy.deepcopy(base_config())
    data.update(overrides)
    return CerebrumConfig.model_validate(data)


def test_valid_config_applies_defaults() -> None:
    config = _build()
    assert config.runtime.isolation == "worktree"
    assert config.runtime.parallelism == 4
    assert config.runtime.test_timeout_multiplier == 8.0
    assert config.baseline.require_green is True
    assert config.targeting.strategy == "coverage"
    assert config.targeting.max_mutants_per_run == 50
    assert config.mutation.operator == "llm"
    assert config.mutation.mutants_per_target == 1
    module = config.modules[0]
    assert module.coverage is None
    assert module.exclude == []


def test_after_run_defaults_to_none() -> None:
    config = _build()
    assert config.after_run is None


def test_after_run_accepts_command_string() -> None:
    config = _build(after_run="python scripts/push_run.py")
    assert config.after_run == "python scripts/push_run.py"


def test_unknown_top_level_key_rejected() -> None:
    with pytest.raises(ValidationError, match="frobnicate"):
        _build(frobnicate=True)


def test_unknown_module_key_rejected() -> None:
    data = copy.deepcopy(base_config())
    data["modules"][0]["typo"] = 1
    with pytest.raises(ValidationError, match="typo"):
        CerebrumConfig.model_validate(data)


def test_invalid_isolation_enum_rejected() -> None:
    with pytest.raises(ValidationError, match="isolation"):
        _build(runtime={"isolation": "vm"})


def test_invalid_strategy_enum_rejected() -> None:
    with pytest.raises(ValidationError, match="strategy"):
        _build(targeting={"strategy": "bogus"})


def test_missing_required_module_field_rejected() -> None:
    data = copy.deepcopy(base_config())
    del data["modules"][0]["test"]
    with pytest.raises(ValidationError, match="test"):
        CerebrumConfig.model_validate(data)


def test_duplicate_module_name_rejected() -> None:
    data = copy.deepcopy(base_config())
    data["modules"].append(copy.deepcopy(data["modules"][0]))
    with pytest.raises(ValidationError, match="duplicate module name"):
        CerebrumConfig.model_validate(data)


def test_coverage_format_without_path_rejected() -> None:
    data = copy.deepcopy(base_config())
    data["modules"][0]["coverage_format"] = "lcov"
    with pytest.raises(ValidationError, match="coverage_format.*coverage_path"):
        CerebrumConfig.model_validate(data)


def test_coverage_path_without_format_rejected() -> None:
    data = copy.deepcopy(base_config())
    data["modules"][0]["coverage_path"] = "coverage/lcov.info"
    with pytest.raises(ValidationError, match="coverage_format.*coverage_path"):
        CerebrumConfig.model_validate(data)


def test_non_positive_budget_rejected() -> None:
    with pytest.raises(ValidationError, match="budget_usd"):
        _build(mutation={"model": "m", "budget_usd": 0})


def test_parallelism_below_one_rejected() -> None:
    with pytest.raises(ValidationError, match="parallelism"):
        _build(runtime={"parallelism": 0})


def test_timeout_multiplier_below_one_rejected() -> None:
    with pytest.raises(ValidationError, match="test_timeout_multiplier"):
        _build(runtime={"test_timeout_multiplier": 0.5})


def test_empty_modules_rejected() -> None:
    with pytest.raises(ValidationError, match="modules"):
        _build(modules=[])


def _module(**overrides: Any) -> Module:
    data = {
        "name": "backend",
        "root": "backend",
        "language": "javascript",
        "install": "npm ci",
        "test": "npm test",
        "source": ["routes/**/*.js", "services/**/*.js"],
        "exclude": ["**/*.test.js", "**/__tests__/**"],
    }
    data.update(overrides)
    return Module.model_validate(data)


def test_resolve_sources_honors_root_and_exclude(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    (backend / "routes").mkdir(parents=True)
    (backend / "services").mkdir(parents=True)
    (backend / "__tests__").mkdir(parents=True)
    (backend / "routes" / "a.js").write_text("//", encoding="utf-8")
    (backend / "routes" / "a.test.js").write_text("//", encoding="utf-8")
    (backend / "services" / "c.js").write_text("//", encoding="utf-8")
    (backend / "__tests__" / "b.test.js").write_text("//", encoding="utf-8")

    resolved = _module().resolve_sources(tmp_path)
    names = {p.relative_to(tmp_path).as_posix() for p in resolved}
    assert names == {"backend/routes/a.js", "backend/services/c.js"}


def test_resolve_sources_zero_match_warns(tmp_path: Path) -> None:
    (tmp_path / "backend").mkdir()
    module = _module(source=["nonexistent/**/*.js"], exclude=[])
    with pytest.warns(ZeroMatchWarning, match="matched no files"):
        assert module.resolve_sources(tmp_path) == []
