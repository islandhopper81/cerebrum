"""CLI tests for `cerebrum report`, and an end-to-end `cerebrum run` history check.

Deterministic: LLM-backed classes (`LLMOperator`, `TestSuggester`) are stubbed
via monkeypatch at their `cerebrum.cli` import site, so no network or API key
is needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from cerebrum.cli import main
from cerebrum.execute.models import MutantRecord
from cerebrum.execute.store import append_record
from cerebrum.generate.operator import MutantProposal, MutationTarget
from cerebrum.report.history import record_run
from cerebrum.report.models import RunSummary
from cerebrum.report.survivors import SurvivorEntry
from tests.support import init_git_repo, make_patch


def _write_project(tmp_path: Path) -> Path:
    module_dir = tmp_path / "backend"
    source = module_dir / "routes" / "meals.js"
    source.parent.mkdir(parents=True)
    source.write_text("// x\n// y\n", encoding="utf-8")

    config: dict[str, Any] = {
        "version": 1,
        "project": "Demo",
        "modules": [
            {
                "name": "backend",
                "root": "backend",
                "language": "javascript",
                "install": "echo installing",
                "test": "echo testing",
                "source": ["routes/**/*.js"],
            }
        ],
        "mutation": {"model": "claude-sonnet-5", "budget_usd": 10},
    }
    path = tmp_path / "cerebrum.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def _killed_record(line: int) -> MutantRecord:
    return MutantRecord(
        file="routes/meals.js",
        line=line,
        diff="d",
        mutation_type="logic",
        status="KILLED",
        covering_tests="npm test",
        rationale="r",
        duration_seconds=0.1,
        severity="medium",
    )


def _survived_record(line: int) -> MutantRecord:
    return MutantRecord(
        file="routes/meals.js",
        line=line,
        diff="d",
        mutation_type="boundary",
        status="SURVIVED",
        covering_tests="npm test",
        rationale="off by one",
        duration_seconds=0.1,
        severity="high",
    )


def _seed_run(
    repo_root: Path, run_id: str, started_at: str, records: list[MutantRecord]
) -> None:
    for record in records:
        append_record(repo_root, record, run_id=run_id)
    killed = sum(1 for r in records if r.status == "KILLED")
    survived = sum(1 for r in records if r.status == "SURVIVED")
    total = killed + survived
    summary = RunSummary(
        run_id=run_id,
        started_at=started_at,
        module="backend",
        strategy="coverage",
        commit="abc123",
        killed=killed,
        survived=survived,
        timeout=0,
        build_error=0,
        no_coverage=0,
        mutation_score=(killed / total) if total else None,
        avg_survivor_severity=None,
        covered_lines=None,
        instrumented_lines=None,
        coverage_pct=None,
        duration_seconds=1.0,
    )
    record_run(repo_root, summary, records)


def test_report_with_no_history_reports_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_project(tmp_path)

    code = main(["report", "-c", str(path)])

    assert code == 0
    assert "no run history yet" in capsys.readouterr().out


def test_report_trend_lists_runs_most_recent_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_project(tmp_path)
    _seed_run(tmp_path, "run-1", "2026-01-01T00:00:00+00:00", [_killed_record(1)])
    _seed_run(
        tmp_path,
        "run-2",
        "2026-01-02T00:00:00+00:00",
        [_killed_record(1), _survived_record(2)],
    )

    code = main(["report", "-c", str(path), "--trend"])

    assert code == 0
    lines = capsys.readouterr().out.splitlines()
    assert "Trend: backend" in lines[0]
    assert "2026-01-02" in lines[1]
    assert "2026-01-01" in lines[2]


class _FakeSuggester:
    def __init__(self, model: str, budget_usd: float) -> None:
        pass

    def suggest(self, entry: SurvivorEntry) -> str | None:
        return f"assert {entry.file}:{entry.line}"


def test_report_survivors_lists_entries_with_suggested_tests(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_project(tmp_path)
    _seed_run(
        tmp_path,
        "run-1",
        "2026-01-01T00:00:00+00:00",
        [_killed_record(1), _survived_record(2)],
    )
    monkeypatch.setattr("cerebrum.cli.TestSuggester", _FakeSuggester)

    code = main(["report", "-c", str(path), "--survivors"])

    out = capsys.readouterr().out
    assert code == 0
    assert "routes/meals.js:2" in out
    assert "suggested_test" in out
    assert "assert routes/meals.js:2" in out


class _FailingSuggester:
    def __init__(self, model: str, budget_usd: float) -> None:
        pass

    def suggest(self, entry: SurvivorEntry) -> str | None:
        return None


def test_report_survivors_reports_when_suggestion_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_project(tmp_path)
    _seed_run(tmp_path, "run-1", "2026-01-01T00:00:00+00:00", [_survived_record(2)])
    monkeypatch.setattr("cerebrum.cli.TestSuggester", _FailingSuggester)

    code = main(["report", "-c", str(path), "--survivors"])

    out = capsys.readouterr().out
    assert code == 0
    assert "could not generate" in out


class _FakeOperatorFactory:
    """Stands in for LLMOperator's constructor signature so `cerebrum run` can
    be driven end-to-end with no real LLM call."""

    def __init__(self, diff: str) -> None:
        self._diff = diff

    def __call__(self, model: str, budget_usd: float) -> _FakeOperatorFactory:
        return self

    def propose(self, target: MutationTarget) -> MutantProposal | None:
        return MutantProposal(
            diff=self._diff,
            mutation_type="logic",
            rationale="test mutant",
            equivalent=False,
            severity="high",
        )


def test_run_end_to_end_records_history_and_prints_score_delta(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # module.root is "." so app.py sits at the worktree root, matching the
    # diff's a/app.py b/app.py paths -- git apply always runs at the worktree
    # root, not module.root.
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    cov = tmp_path / "coverage" / "lcov.info"
    cov.parent.mkdir(parents=True)
    cov.write_text("SF:app.py\nDA:1,5\nend_of_record\n", encoding="utf-8")
    init_git_repo(tmp_path, {})

    config: dict[str, Any] = {
        "version": 1,
        "project": "Demo",
        "modules": [
            {
                "name": "backend",
                "root": ".",
                "language": "python",
                "install": "echo installing",
                "test": "echo testing",
                "coverage_format": "lcov",
                "coverage_path": "coverage/lcov.info",
                "source": ["*.py"],
            }
        ],
        "mutation": {"model": "claude-sonnet-5", "budget_usd": 10},
    }
    path = tmp_path / "cerebrum.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")

    diff = make_patch("app.py", "VALUE = 1\n", "VALUE = 2\n")
    monkeypatch.setattr("cerebrum.cli.LLMOperator", _FakeOperatorFactory(diff))

    code1 = main(["run", "-c", str(path), "--module", "backend"])
    assert code1 == 0
    out1 = capsys.readouterr().out
    assert "first run for this module" in out1

    run_dirs = list((tmp_path / ".cerebrum" / "runs").iterdir())
    assert len(run_dirs) == 1
    assert (tmp_path / ".cerebrum" / "history.sqlite").exists()

    code2 = main(["run", "-c", str(path), "--module", "backend"])
    assert code2 == 0
    out2 = capsys.readouterr().out
    assert "vs last run" in out2
