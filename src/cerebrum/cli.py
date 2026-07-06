"""Command-line entry point for Cerebrum."""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
