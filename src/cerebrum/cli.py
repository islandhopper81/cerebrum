"""Command-line entry point for Cerebrum."""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

from cerebrum.baseline.models import BaselineResult
from cerebrum.baseline.runner import BaselineError, run_baseline
from cerebrum.config.loader import DEFAULT_CONFIG_NAME, ConfigError, load_config
from cerebrum.config.model import CerebrumConfig, Module
from cerebrum.exec.git import GitError
from cerebrum.execute.lifecycle import NoMutantProduced, run_mutant
from cerebrum.execute.runner import run_targets
from cerebrum.execute.select import select_target
from cerebrum.execute.store import append_record
from cerebrum.execute.targeting import TargetingContext, TargetingError, select_targets
from cerebrum.execute.worktree import WorktreeError
from cerebrum.generate.llm import LLMOperator, LLMOperatorError


def _cmd_validate(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    repo_root = config_path.resolve().parent
    print(f"Config: {config_path} (project: {config.project}, version: {config.version})")
    print("Modules:")
    for module in config.modules:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            count = len(module.resolve_sources(repo_root))
        note = "  (warning: no source files matched)" if caught else ""
        print(f"  - {module.name} [{module.language}]: {count} source files{note}")
    print("Valid.")
    return 0


def _cmd_baseline(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    repo_root = config_path.resolve().parent
    modules = config.modules
    if args.module is not None:
        modules = [m for m in modules if m.name == args.module]
        if not modules:
            print(f"no module named '{args.module}' in {config_path}", file=sys.stderr)
            return 1

    print(f"Baseline: {config_path} (project: {config.project})")
    exit_code = 0
    for module in modules:
        try:
            result = run_baseline(module, repo_root, config.baseline, config.runtime)
        except BaselineError as exc:
            print(str(exc), file=sys.stderr)
            exit_code = 1
            continue
        status = "green" if result.passed else "RED (require_green off)"
        print(
            f"  - {module.name} [{module.language}]: {status}, "
            f"{result.test_duration_seconds:.2f}s, "
            f"{len(result.covered_lines)} covered files, "
            f"{_count_uncovered(result)} instrumented-but-uncovered lines"
        )
    return exit_code


def _cmd_mutate(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if (args.file is None) != (args.line is None):
        print("--file and --line must be given together", file=sys.stderr)
        return 1

    module = _select_module(config, args.module, config_path)
    if module is None:
        return 1

    repo_root = config_path.resolve().parent
    try:
        baseline = run_baseline(module, repo_root, config.baseline, config.runtime)
    except BaselineError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    target = select_target(
        baseline, module, repo_root, file=args.file, line=args.line
    )
    if target is None:
        print(f"module '{module.name}': no covered lines to mutate")
        return 0

    operator = LLMOperator(
        model=config.mutation.model, budget_usd=config.mutation.budget_usd
    )
    print(f"Mutate: {config_path} (project: {config.project}, module: {module.name})")
    try:
        record = run_mutant(
            module, repo_root, baseline, config.runtime, operator, target
        )
    except NoMutantProduced as exc:
        print(f"  {exc}")
        return 0
    except (WorktreeError, GitError, LLMOperatorError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    out = append_record(repo_root, record)
    print(
        f"  {record.file}:{record.line} → {record.status} "
        f"({record.mutation_type or 'n/a'}, {record.duration_seconds:.2f}s)  "
        f"→ recorded in {out}"
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    module = _select_module(config, args.module, config_path)
    if module is None:
        return 1

    repo_root = config_path.resolve().parent
    try:
        baseline = run_baseline(module, repo_root, config.baseline, config.runtime)
    except BaselineError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    strategy = "changed" if args.diff is not None else config.targeting.strategy
    ctx = TargetingContext(
        baseline=baseline,
        module=module,
        repo_root=repo_root,
        cap=config.targeting.max_mutants_per_run,
        diff_range=args.diff,
    )
    try:
        targets = select_targets(strategy, ctx)
    except TargetingError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not targets:
        print(f"module '{module.name}': no targets to mutate")
        return 0

    operator = LLMOperator(
        model=config.mutation.model, budget_usd=config.mutation.budget_usd
    )
    print(
        f"Run: {config_path} (project: {config.project}, module: {module.name}, "
        f"strategy: {strategy}, targets: {len(targets)})"
    )
    try:
        records = run_targets(module, repo_root, baseline, config.runtime, operator, targets)
    except (WorktreeError, GitError, LLMOperatorError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    counts: dict[str, int] = {}
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
        print(
            f"  {record.file}:{record.line} → {record.status} "
            f"({record.mutation_type or 'n/a'}, {record.duration_seconds:.2f}s)"
        )
    summary = ", ".join(f"{n} {status.lower()}" for status, n in sorted(counts.items()))
    print(f"{len(records)} mutants: {summary or 'none scored'}")
    return 0


def _select_module(
    config: CerebrumConfig, name: str | None, config_path: Path
) -> Module | None:
    if name is not None:
        for module in config.modules:
            if module.name == name:
                return module
        print(f"no module named '{name}' in {config_path}", file=sys.stderr)
        return None
    if len(config.modules) > 1:
        print(
            "config defines multiple modules; specify one with --module",
            file=sys.stderr,
        )
        return None
    return config.modules[0]


def _count_uncovered(result: BaselineResult) -> int:
    return sum(
        len(instrumented - result.covered_lines.get(file, set()))
        for file, instrumented in result.instrumented_lines.items()
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cerebrum", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Parse and validate a cerebrum.yaml file")
    validate.add_argument(
        "-c",
        "--config",
        default=DEFAULT_CONFIG_NAME,
        help=f"path to config file (default: ./{DEFAULT_CONFIG_NAME})",
    )
    validate.set_defaults(func=_cmd_validate)

    baseline = sub.add_parser(
        "baseline",
        help="Run a module's baseline: install, test, require-green, capture coverage",
    )
    baseline.add_argument(
        "-c",
        "--config",
        default=DEFAULT_CONFIG_NAME,
        help=f"path to config file (default: ./{DEFAULT_CONFIG_NAME})",
    )
    baseline.add_argument(
        "--module",
        default=None,
        help="only run this module by name (default: all modules)",
    )
    baseline.set_defaults(func=_cmd_baseline)

    mutate = sub.add_parser(
        "mutate",
        help="Run one mutant end-to-end: select → generate → apply → test → classify",
    )
    mutate.add_argument(
        "-c",
        "--config",
        default=DEFAULT_CONFIG_NAME,
        help=f"path to config file (default: ./{DEFAULT_CONFIG_NAME})",
    )
    mutate.add_argument(
        "--module",
        default=None,
        help="module to mutate (required when the config defines more than one)",
    )
    mutate.add_argument(
        "--file",
        default=None,
        help="target file to mutate (repo-relative; requires --line)",
    )
    mutate.add_argument(
        "--line",
        type=int,
        default=None,
        help="target line to mutate (1-based; requires --file)",
    )
    mutate.set_defaults(func=_cmd_mutate)

    run = sub.add_parser(
        "run",
        help="Sweep a module: pick targets (config strategy, or --diff) and mutate each one",
    )
    run.add_argument(
        "-c",
        "--config",
        default=DEFAULT_CONFIG_NAME,
        help=f"path to config file (default: ./{DEFAULT_CONFIG_NAME})",
    )
    run.add_argument(
        "--module",
        default=None,
        help="module to run (required when the config defines more than one)",
    )
    run.add_argument(
        "--diff",
        default=None,
        metavar="<base>..<head>",
        help="mutate only lines changed in this range (forces the 'changed' strategy)",
    )
    run.set_defaults(func=_cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
