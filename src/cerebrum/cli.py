"""Command-line entry point for Cerebrum."""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

from cerebrum.baseline.models import BaselineResult
from cerebrum.baseline.runner import BaselineError, run_baseline
from cerebrum.config.loader import DEFAULT_CONFIG_NAME, ConfigError, load_config


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
