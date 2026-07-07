"""Pluggable targeting: choose which covered lines to mutate.

Given a module and baseline, produce a list of ``MutationTarget``s. Strategies are
looked up in a registry, so adding one is registering a function — call sites in
:mod:`cerebrum.cli` never change. ``coverage`` and ``changed`` are implemented;
``llm-risk`` (the experiment's risk-ranking prompt) and ``all`` are registered
stubs that raise :class:`TargetingError` until implemented, so a config already
set to either fails clearly rather than silently falling back to something else.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cerebrum.baseline.models import BaselineResult
from cerebrum.config.model import Module
from cerebrum.exec import git
from cerebrum.execute.select import build_targets
from cerebrum.generate.operator import MutationTarget


class TargetingError(Exception):
    """Raised when a strategy cannot produce targets — unimplemented or unknown
    strategy, or a required option (e.g. a diff range) is missing."""


@dataclass(frozen=True)
class TargetingContext:
    baseline: BaselineResult
    module: Module
    repo_root: Path
    cap: int
    diff_range: str | None = None


StrategyFn = Callable[[TargetingContext], list[MutationTarget]]


def _module_source_files(ctx: TargetingContext) -> set[Path]:
    return {p.resolve() for p in ctx.module.resolve_sources(ctx.repo_root)}


def _coverage(ctx: TargetingContext) -> list[MutationTarget]:
    sources = _module_source_files(ctx)
    targets: list[MutationTarget] = []
    for path in sorted(ctx.baseline.covered_lines):
        if path not in sources:
            continue
        lines = ctx.baseline.covered_lines[path]
        if not lines:
            continue
        targets.extend(build_targets(path, lines, ctx.repo_root, ctx.module.language))
    return targets[: ctx.cap]


def _changed(ctx: TargetingContext) -> list[MutationTarget]:
    if ctx.diff_range is None:
        raise TargetingError(
            "'changed' strategy requires a diff range (--diff <base>..<head>)"
        )
    sources = _module_source_files(ctx)
    changed = git.changed_lines(ctx.repo_root, ctx.diff_range)
    targets: list[MutationTarget] = []
    for path in sorted(changed):
        if path not in sources:
            continue
        lines = changed[path] & ctx.baseline.covered_lines.get(path, set())
        if not lines:
            continue
        targets.extend(build_targets(path, lines, ctx.repo_root, ctx.module.language))
    return targets[: ctx.cap]


def _llm_risk(ctx: TargetingContext) -> list[MutationTarget]:
    raise TargetingError(
        "strategy 'llm-risk' is not implemented yet (M1 supports coverage, changed)"
    )


def _all(ctx: TargetingContext) -> list[MutationTarget]:
    raise TargetingError(
        "strategy 'all' is not implemented yet (M1 supports coverage, changed)"
    )


_STRATEGIES: dict[str, StrategyFn] = {
    "coverage": _coverage,
    "changed": _changed,
    "llm-risk": _llm_risk,
    "all": _all,
}


def select_targets(strategy: str, ctx: TargetingContext) -> list[MutationTarget]:
    try:
        strategy_fn = _STRATEGIES[strategy]
    except KeyError:
        raise TargetingError(f"unknown targeting strategy: '{strategy}'") from None
    return strategy_fn(ctx)
