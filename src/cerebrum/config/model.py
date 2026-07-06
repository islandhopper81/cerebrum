"""Typed, validated model of ``cerebrum.yaml``.

This is the hard API the rest of the engine (baseline, targeting, execution,
reporting) imports. Everything codebase-specific about a target repo is declared
here; the engine itself stays language-agnostic.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Isolation = Literal["worktree", "docker", "clone"]
CoverageFormat = Literal["lcov", "cobertura", "coverage.py", "json"]
Strategy = Literal["coverage", "changed", "llm-risk", "all"]
Operator = Literal["llm"]


class ZeroMatchWarning(UserWarning):
    """Emitted when a module's source globs match no files."""


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Runtime(_Base):
    isolation: Isolation = "worktree"
    parallelism: int = Field(default=4, ge=1)
    test_timeout_multiplier: float = Field(default=8.0, ge=1)


class Baseline(_Base):
    require_green: bool = True


class Module(_Base):
    name: str
    root: str
    language: str
    install: str
    test: str
    coverage: str | None = None
    coverage_format: CoverageFormat | None = None
    coverage_path: str | None = None
    source: list[str] = Field(min_length=1)
    exclude: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coverage_pairing(self) -> Module:
        if (self.coverage_format is None) != (self.coverage_path is None):
            raise ValueError(
                f"module '{self.name}': 'coverage_format' and 'coverage_path' must be "
                "set together (define both, or neither)"
            )
        return self

    def resolve_sources(self, repo_root: Path) -> list[Path]:
        """Expand ``source`` minus ``exclude``, relative to ``repo_root / root``.

        Returns matched files (not directories), sorted. A glob set that matches
        nothing emits a :class:`ZeroMatchWarning` rather than raising — an empty
        module is a warning, not a hard error.
        """
        base = repo_root / self.root
        included = {
            p for pattern in self.source for p in base.glob(pattern) if p.is_file()
        }
        excluded = {p for pattern in self.exclude for p in base.glob(pattern)}
        result = sorted(included - excluded)
        if not result:
            warnings.warn(
                f"module '{self.name}': source globs matched no files under {base}",
                ZeroMatchWarning,
                stacklevel=2,
            )
        return result


class Targeting(_Base):
    strategy: Strategy = "coverage"
    max_mutants_per_run: int = Field(default=50, ge=1)


class Mutation(_Base):
    operator: Operator = "llm"
    model: str
    budget_usd: float = Field(gt=0)
    mutants_per_target: int = Field(default=1, ge=1)


class CerebrumConfig(_Base):
    version: int
    project: str
    runtime: Runtime = Field(default_factory=Runtime)
    baseline: Baseline = Field(default_factory=Baseline)
    modules: list[Module] = Field(min_length=1)
    targeting: Targeting = Field(default_factory=Targeting)
    mutation: Mutation

    @model_validator(mode="after")
    def _unique_module_names(self) -> CerebrumConfig:
        seen: set[str] = set()
        for module in self.modules:
            if module.name in seen:
                raise ValueError(f"duplicate module name: '{module.name}'")
            seen.add(module.name)
        return self
