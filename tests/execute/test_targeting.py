"""Unit tests for pluggable targeting strategies."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cerebrum.execute.targeting import TargetingContext, TargetingError, select_targets
from tests.support import init_git_repo, make_baseline, make_module


def _write(repo: Path, rel: str, text: str) -> Path:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path.resolve()


def test_coverage_returns_all_covered_lines_sorted(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.py", "1\n2\n3\n")
    b = _write(tmp_path, "b.py", "1\n2\n")
    baseline = make_baseline({a: {3, 1}, b: {2}})
    ctx = TargetingContext(
        baseline=baseline, module=make_module(), repo_root=tmp_path, cap=50
    )

    targets = select_targets("coverage", ctx)

    assert [(t.file, t.line) for t in targets] == [
        (Path("a.py"), 1),
        (Path("a.py"), 3),
        (Path("b.py"), 2),
    ]


def test_coverage_respects_cap(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.py", "1\n2\n3\n")
    baseline = make_baseline({a: {1, 2, 3}})
    ctx = TargetingContext(
        baseline=baseline, module=make_module(), repo_root=tmp_path, cap=2
    )

    targets = select_targets("coverage", ctx)

    assert len(targets) == 2


def test_coverage_excludes_files_outside_module_source_globs(tmp_path: Path) -> None:
    py = _write(tmp_path, "a.py", "1\n2\n")
    txt = _write(tmp_path, "a.txt", "1\n2\n")
    baseline = make_baseline({py: {1}, txt: {1}})
    ctx = TargetingContext(
        baseline=baseline,
        module=make_module(source=["**/*.py"]),
        repo_root=tmp_path,
        cap=50,
    )

    targets = select_targets("coverage", ctx)

    assert [(t.file, t.line) for t in targets] == [(Path("a.py"), 1)]


def test_changed_intersects_diff_with_covered_lines(tmp_path: Path) -> None:
    init_git_repo(tmp_path, {"a.py": "one\ntwo\n"})
    (tmp_path / "a.py").write_text("one\nCHANGED\nthree\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "change"], cwd=tmp_path, check=True, capture_output=True
    )

    a = (tmp_path / "a.py").resolve()
    baseline = make_baseline({a: {2}})  # line 3 is also changed but not covered
    ctx = TargetingContext(
        baseline=baseline,
        module=make_module(),
        repo_root=tmp_path,
        cap=50,
        diff_range="HEAD~1..HEAD",
    )

    targets = select_targets("changed", ctx)

    assert [(t.file, t.line) for t in targets] == [(Path("a.py"), 2)]


def test_changed_without_diff_range_raises(tmp_path: Path) -> None:
    baseline = make_baseline({})
    ctx = TargetingContext(
        baseline=baseline, module=make_module(), repo_root=tmp_path, cap=50
    )

    with pytest.raises(TargetingError):
        select_targets("changed", ctx)


@pytest.mark.parametrize("strategy", ["llm-risk", "all"])
def test_unimplemented_strategies_raise(tmp_path: Path, strategy: str) -> None:
    baseline = make_baseline({})
    ctx = TargetingContext(
        baseline=baseline, module=make_module(), repo_root=tmp_path, cap=50
    )

    with pytest.raises(TargetingError):
        select_targets(strategy, ctx)


def test_unknown_strategy_raises(tmp_path: Path) -> None:
    baseline = make_baseline({})
    ctx = TargetingContext(
        baseline=baseline, module=make_module(), repo_root=tmp_path, cap=50
    )

    with pytest.raises(TargetingError):
        select_targets("nonsense", ctx)
