"""Command-line entry point for Cerebrum."""

from __future__ import annotations

import argparse
import secrets
import sys
import textwrap
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path

from cerebrum.baseline.models import BaselineResult
from cerebrum.baseline.runner import BaselineError, run_baseline
from cerebrum.config.loader import DEFAULT_CONFIG_NAME, ConfigError, load_config
from cerebrum.config.model import CerebrumConfig, Module
from cerebrum.exec.command import run_command
from cerebrum.exec.git import GitError, current_commit
from cerebrum.execute.lifecycle import NoMutantProduced, run_mutant
from cerebrum.execute.runner import run_targets
from cerebrum.execute.select import select_target
from cerebrum.execute.store import (
    append_record,
    build_coverage_rows,
    load_records,
    write_coverage,
)
from cerebrum.execute.targeting import TargetingContext, TargetingError, select_targets
from cerebrum.execute.worktree import WorktreeError
from cerebrum.generate.llm import LLMOperator, LLMOperatorError
from cerebrum.report import (
    RunSummary,
    TestSuggester,
    TestSuggesterError,
    average_survivor_severity,
    build_survivor_report,
    compute_score,
    record_run,
    recurring_survivors,
    trend,
)


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
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
    print(
        f"Run: {config_path} (project: {config.project}, module: {module.name}, "
        f"strategy: {strategy}, targets: {len(targets)}, run: {run_id})"
    )
    start = time.perf_counter()
    try:
        records = run_targets(
            module, repo_root, baseline, config.runtime, operator, targets, run_id
        )
    except (WorktreeError, GitError, LLMOperatorError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    duration = time.perf_counter() - start

    counts: dict[str, int] = {}
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
        print(
            f"  {record.file}:{record.line} → {record.status} "
            f"({record.mutation_type or 'n/a'}, {record.duration_seconds:.2f}s)"
        )
    summary = ", ".join(f"{n} {status.lower()}" for status, n in sorted(counts.items()))
    print(f"{len(records)} mutants: {summary or 'none scored'}")

    score = compute_score(records)
    previous = trend(repo_root, module.name, limit=1)
    covered_total = sum(len(lines) for lines in baseline.covered_lines.values())
    instrumented_total = sum(len(lines) for lines in baseline.instrumented_lines.values())
    coverage_pct = covered_total / instrumented_total if instrumented_total else None
    run_summary = RunSummary(
        run_id=run_id,
        started_at=datetime.now(UTC).isoformat(),
        module=module.name,
        strategy=strategy,
        commit=current_commit(repo_root),
        killed=counts.get("KILLED", 0),
        survived=counts.get("SURVIVED", 0),
        timeout=counts.get("TIMEOUT", 0),
        build_error=counts.get("BUILD_ERROR", 0),
        no_coverage=counts.get("NO_COVERAGE", 0),
        mutation_score=score,
        avg_survivor_severity=average_survivor_severity(records),
        covered_lines=covered_total,
        instrumented_lines=instrumented_total,
        coverage_pct=coverage_pct,
        duration_seconds=duration,
    )
    record_run(repo_root, run_summary, records)
    write_coverage(
        repo_root,
        run_id,
        build_coverage_rows(
            baseline.covered_lines, baseline.instrumented_lines, records, repo_root
        ),
    )

    if config.after_run:
        after_result = run_command(config.after_run, cwd=repo_root)
        if after_result.exit_code != 0:
            print(
                f"after_run: '{config.after_run}' exited {after_result.exit_code} "
                f"(non-fatal): {after_result.stderr.strip()[:500]}",
                file=sys.stderr,
            )

    if score is None:
        print("score: n/a (no valid mutants)")
    elif previous and previous[0].mutation_score is not None:
        delta = score - previous[0].mutation_score
        arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "→")
        print(f"score: {score:.2f} ({arrow} {delta:+.2f} vs last run)")
    else:
        print(f"score: {score:.2f} (first run for this module)")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
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

    if args.trend is not None:
        limit = args.trend if isinstance(args.trend, int) else 20
        runs = trend(repo_root, module.name, limit=limit)
        if not runs:
            print(f"module '{module.name}': no run history yet")
        else:
            print(f"Trend: {module.name} (last {len(runs)} runs)")
            for run_summary in runs:
                score_str = (
                    f"{run_summary.mutation_score:.2f}"
                    if run_summary.mutation_score is not None
                    else "n/a"
                )
                sev_str = (
                    f"{run_summary.avg_survivor_severity:.2f}"
                    if run_summary.avg_survivor_severity is not None
                    else "n/a"
                )
                print(
                    f"  {run_summary.started_at}  score={score_str}  "
                    f"killed={run_summary.killed} survived={run_summary.survived}  "
                    f"avg_severity={sev_str}  commit={run_summary.commit or 'n/a'}"
                )

    if args.run_id is not None:
        history = trend(repo_root, module.name, limit=10_000)
        matches = [s for s in history if s.run_id == args.run_id]
        if not matches:
            print(f"no run '{args.run_id}' found for module '{module.name}'", file=sys.stderr)
            return 1
        run_summary = matches[0]
    else:
        latest = trend(repo_root, module.name, limit=1)
        if not latest:
            print(f"module '{module.name}': no run history yet")
            return 0
        run_summary = latest[0]
    run_id = run_summary.run_id

    if not args.trend and not args.survivors:
        score_str = (
            f"{run_summary.mutation_score:.2f}" if run_summary.mutation_score is not None else "n/a"
        )
        print(
            f"Run {run_id}: score={score_str}, killed={run_summary.killed}, "
            f"survived={run_summary.survived}"
        )

    if args.survivors:
        records = load_records(repo_root, run_id)
        recurrence = recurring_survivors(repo_root, module.name, run_id)
        survivors = build_survivor_report(records, recurrence)
        if not survivors:
            print("No survivors in this run.")
            return 0

        suggester = TestSuggester(
            model=config.mutation.model, budget_usd=config.mutation.budget_usd
        )
        print(f"Survivors: {module.name} (run {run_id})")
        for entry in survivors:
            print(
                f"  {entry.file}:{entry.line} [{entry.severity}] ({entry.mutation_type}) "
                f"— surviving {entry.consecutive_runs} run(s) in a row"
            )
            print(f"    rationale: {entry.rationale}")
            print(f"    diff:\n{textwrap.indent(entry.diff, '      ')}")
            try:
                suggested = suggester.suggest(entry)
            except TestSuggesterError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if suggested is None:
                print("    suggested_test: could not generate")
            else:
                print(f"    suggested_test:\n{textwrap.indent(suggested, '      ')}")

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

    report = sub.add_parser(
        "report",
        help="Show a run's score, survivor report, and/or trend across runs",
    )
    report.add_argument(
        "-c",
        "--config",
        default=DEFAULT_CONFIG_NAME,
        help=f"path to config file (default: ./{DEFAULT_CONFIG_NAME})",
    )
    report.add_argument(
        "--module",
        default=None,
        help="module to report on (required when the config defines more than one)",
    )
    report.add_argument(
        "--run-id",
        default=None,
        help="report on this run (default: the latest run for the module)",
    )
    report.add_argument(
        "--survivors",
        action="store_true",
        help="print the survivor report, generating a suggested test for each",
    )
    report.add_argument(
        "--trend",
        nargs="?",
        type=int,
        const=20,
        default=None,
        metavar="N",
        help="print the last N runs' scores (default 20 when given with no value)",
    )
    report.set_defaults(func=_cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy codepage (e.g. cp1252) that can't
    # encode characters like the arrows printed by `run`/`report` output,
    # crashing after mutation testing has already completed. Force utf-8
    # regardless of the invoking environment's codepage/locale.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
