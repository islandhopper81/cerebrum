"""Unit tests for pluggable targeting strategies."""

from __future__ import annotations

import random
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


def test_coverage_distributes_fairly_when_files_fit_within_cap(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.py", "1\n2\n3\n4\n")
    b = _write(tmp_path, "b.py", "1\n2\n")
    c = _write(tmp_path, "c.py", "1\n2\n3\n")
    baseline = make_baseline({a: {1, 2, 3, 4}, b: {1, 2}, c: {1, 2, 3}})
    ctx = TargetingContext(
        baseline=baseline,
        module=make_module(),
        repo_root=tmp_path,
        cap=3,
        rng=random.Random(1),
    )

    targets = select_targets("coverage", ctx)

    files = [t.file for t in targets]
    assert sorted(files) == [Path("a.py"), Path("b.py"), Path("c.py")]  # every file present
    assert len(targets) == 3  # exactly one target per file, none starved


def test_coverage_selects_random_subset_of_files_when_files_exceed_cap(
    tmp_path: Path,
) -> None:
    paths = {c: _write(tmp_path, f"{c}.py", "1\n") for c in "abcde"}
    baseline = make_baseline({p: {1} for p in paths.values()})
    ctx = TargetingContext(
        baseline=baseline,
        module=make_module(),
        repo_root=tmp_path,
        cap=2,
        rng=random.Random(1234),
    )

    targets = select_targets("coverage", ctx)

    assert len(targets) == 2
    assert len({t.file for t in targets}) == 2  # 2 distinct files, matching the cap
    assert sorted(t.file for t in targets) == [Path("a.py"), Path("d.py")]


def test_coverage_fixed_seed_is_deterministic(tmp_path: Path) -> None:
    paths = {c: _write(tmp_path, f"{c}.py", "1\n") for c in "abcde"}
    baseline = make_baseline({p: {1} for p in paths.values()})

    def _run() -> list[tuple[Path, int]]:
        ctx = TargetingContext(
            baseline=baseline,
            module=make_module(),
            repo_root=tmp_path,
            cap=2,
            rng=random.Random(1234),
        )
        return [(t.file, t.line) for t in select_targets("coverage", ctx)]

    assert _run() == _run()


def test_coverage_different_seeds_can_select_different_lines(tmp_path: Path) -> None:
    big = _write(tmp_path, "big.py", "\n".join(str(n) for n in range(1, 21)) + "\n")
    small = _write(tmp_path, "small.py", "1\n")
    baseline = make_baseline({big: set(range(1, 21)), small: {1}})

    def _run(seed: int) -> set[tuple[Path, int]]:
        ctx = TargetingContext(
            baseline=baseline,
            module=make_module(),
            repo_root=tmp_path,
            cap=5,
            rng=random.Random(seed),
        )
        return {(t.file, t.line) for t in select_targets("coverage", ctx)}

    assert _run(1) != _run(2)
    # neither seed starves the small file, even though big.py has far more lines
    assert (Path("small.py"), 1) in _run(1)
    assert (Path("small.py"), 1) in _run(2)


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


def test_changed_distributes_fairly_when_files_fit_within_cap(tmp_path: Path) -> None:
    init_git_repo(
        tmp_path,
        {"a.py": "one\ntwo\n", "b.py": "one\ntwo\n", "c.py": "one\ntwo\n"},
    )
    for name in ("a", "b", "c"):
        (tmp_path / f"{name}.py").write_text("CHANGED\nCHANGED\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "change"], cwd=tmp_path, check=True, capture_output=True
    )
    paths = {name: (tmp_path / f"{name}.py").resolve() for name in ("a", "b", "c")}
    baseline = make_baseline({p: {1, 2} for p in paths.values()})
    ctx = TargetingContext(
        baseline=baseline,
        module=make_module(),
        repo_root=tmp_path,
        cap=3,
        diff_range="HEAD~1..HEAD",
        rng=random.Random(1),
    )

    targets = select_targets("changed", ctx)

    assert sorted(t.file for t in targets) == [Path("a.py"), Path("b.py"), Path("c.py")]
    assert len(targets) == 3  # exactly one target per file, none starved


def test_changed_selects_random_subset_of_files_when_files_exceed_cap(
    tmp_path: Path,
) -> None:
    names = list("abcde")
    init_git_repo(tmp_path, {f"{n}.py": "one\n" for n in names})
    for n in names:
        (tmp_path / f"{n}.py").write_text("CHANGED\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "change"], cwd=tmp_path, check=True, capture_output=True
    )
    paths = {n: (tmp_path / f"{n}.py").resolve() for n in names}
    baseline = make_baseline({p: {1} for p in paths.values()})
    ctx = TargetingContext(
        baseline=baseline,
        module=make_module(),
        repo_root=tmp_path,
        cap=2,
        diff_range="HEAD~1..HEAD",
        rng=random.Random(1234),
    )

    targets = select_targets("changed", ctx)

    assert len(targets) == 2
    assert len({t.file for t in targets}) == 2
    assert sorted(t.file for t in targets) == [Path("a.py"), Path("d.py")]


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
