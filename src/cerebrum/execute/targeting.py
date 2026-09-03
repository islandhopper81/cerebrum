"""Pluggable targeting: choose which covered lines to mutate.

Given a module and baseline, produce a list of ``MutationTarget``s. Strategies are
looked up in a registry, so adding one is registering a function — call sites in
:mod:`cerebrum.cli` never change. ``coverage`` and ``changed`` are implemented;
``llm-risk`` (the experiment's risk-ranking prompt) and ``all`` are registered
stubs that raise :class:`TargetingError` until implemented, so a config already
set to either fails clearly rather than silently falling back to something else.
"""

from __future__ import annotations

import random
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
    rng: random.Random | None = None


StrategyFn = Callable[[TargetingContext], list[MutationTarget]]


def _module_source_files(ctx: TargetingContext) -> set[Path]:
    return {p.resolve() for p in ctx.module.resolve_sources(ctx.repo_root)}


def _distribute_fairly(
    files_to_lines: dict[Path, set[int]], cap: int, rng: random.Random
) -> dict[Path, set[int]]:
    """Choose up to ``cap`` (file, line) pairs from ``files_to_lines``.

    Every file with eligible lines gets at least one pick, unless there are
    more eligible files than ``cap`` (then ``cap`` files are chosen at random,
    one line each). Any remaining budget beyond one-per-file is distributed
    proportional to each file's eligible-line count (largest remainder
    method), and which specific lines are picked is randomized — so which
    files/lines a run selects need not match a prior run against the same
    inputs.
    """
    total = sum(len(lines) for lines in files_to_lines.values())
    if total <= cap:
        return dict(files_to_lines)

    files = list(files_to_lines)
    if len(files) >= cap:
        chosen_files = rng.sample(files, cap)
        return {path: {rng.choice(sorted(files_to_lines[path]))} for path in chosen_files}

    remainder_budget = cap - len(files)
    shares = {
        path: remainder_budget * len(lines) / total for path, lines in files_to_lines.items()
    }
    floors = {path: int(share) for path, share in shares.items()}
    leftover = remainder_budget - sum(floors.values())
    fractional = [(path, shares[path] - floors[path]) for path in files]
    rng.shuffle(fractional)
    fractional.sort(key=lambda item: item[1], reverse=True)
    for path, _ in fractional[:leftover]:
        floors[path] += 1

    quotas = {path: min(1 + floors[path], len(files_to_lines[path])) for path in files}
    return {
        path: set(rng.sample(sorted(files_to_lines[path]), quotas[path])) for path in files
    }


def _coverage(ctx: TargetingContext) -> list[MutationTarget]:
    sources = _module_source_files(ctx)
    files_to_lines: dict[Path, set[int]] = {}
    for path in sorted(ctx.baseline.covered_lines):
        if path not in sources:
            continue
        lines = ctx.baseline.covered_lines[path]
        if not lines:
            continue
        files_to_lines[path] = lines
    chosen = _distribute_fairly(files_to_lines, ctx.cap, ctx.rng or random.Random())
    targets: list[MutationTarget] = []
    for path in sorted(chosen):
        targets.extend(build_targets(path, chosen[path], ctx.repo_root, ctx.module.language))
    return targets


def _changed(ctx: TargetingContext) -> list[MutationTarget]:
    if ctx.diff_range is None:
        raise TargetingError(
            "'changed' strategy requires a diff range (--diff <base>..<head>)"
        )
    sources = _module_source_files(ctx)
    changed = git.changed_lines(ctx.repo_root, ctx.diff_range)
    files_to_lines: dict[Path, set[int]] = {}
    for path in sorted(changed):
        if path not in sources:
            continue
        lines = changed[path] & ctx.baseline.covered_lines.get(path, set())
        if not lines:
            continue
        files_to_lines[path] = lines
    chosen = _distribute_fairly(files_to_lines, ctx.cap, ctx.rng or random.Random())
    targets: list[MutationTarget] = []
    for path in sorted(chosen):
        targets.extend(build_targets(path, chosen[path], ctx.repo_root, ctx.module.language))
    return targets


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
