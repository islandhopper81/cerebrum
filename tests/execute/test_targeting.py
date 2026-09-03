"""Unit tests for pluggable targeting strategies."""

from __future__ import annotations

import random
import subprocess
from pathlib import Path

import pytest

from cerebrum.execute.targeting import (
    TargetingContext,
    TargetingError,
    _allocate_quotas,
    _weighted_sample_without_replacement,
    select_targets,
)
from tests.support import FakeRiskScorer, init_git_repo, make_baseline, make_module


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


def test_allocate_quotas_matches_prior_distribute_fairly_behavior(tmp_path: Path) -> None:
    files_to_lines = {
        Path("a.py"): {1, 2, 3, 4},
        Path("b.py"): {1, 2},
        Path("c.py"): {1, 2, 3},
    }

    quotas = _allocate_quotas(files_to_lines, cap=3, rng=random.Random(1))

    assert sorted(quotas) == [Path("a.py"), Path("b.py"), Path("c.py")]
    assert all(q >= 1 for q in quotas.values())  # every file present, none starved
    assert sum(quotas.values()) == 3


def test_allocate_quotas_selects_random_subset_when_files_exceed_cap() -> None:
    files_to_lines = {Path(f"{c}.py"): {1} for c in "abcde"}

    quotas = _allocate_quotas(files_to_lines, cap=2, rng=random.Random(1234))

    assert sum(1 for q in quotas.values() if q > 0) == 2


def test_weighted_sample_favors_high_weight_line_across_seeds() -> None:
    lines = [1, 2, 3, 4, 5]
    weights = {1: 100.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0}

    wins = 0
    for seed in range(20):
        chosen = _weighted_sample_without_replacement(lines, weights, k=1, rng=random.Random(seed))
        if chosen == {1}:
            wins += 1

    assert wins >= 16


def test_weighted_sample_never_fully_excludes_a_zero_weight_line() -> None:
    lines = [1, 2, 3, 4, 5]
    weights = {1: 0.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0}

    picked_low_weight_line = False
    for seed in range(50):
        chosen = _weighted_sample_without_replacement(lines, weights, k=1, rng=random.Random(seed))
        if chosen == {1}:
            picked_low_weight_line = True
            break

    assert picked_low_weight_line


def test_llm_risk_requires_a_risk_scorer(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.py", "1\n2\n")
    baseline = make_baseline({a: {1, 2}})
    ctx = TargetingContext(
        baseline=baseline, module=make_module(), repo_root=tmp_path, cap=50, risk_scorer=None
    )

    with pytest.raises(TargetingError):
        select_targets("llm-risk", ctx)


def test_llm_risk_skips_scoring_when_quota_covers_every_candidate(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.py", "1\n2\n")
    baseline = make_baseline({a: {1, 2}})
    scorer = FakeRiskScorer(scores_by_file={})
    ctx = TargetingContext(
        baseline=baseline,
        module=make_module(),
        repo_root=tmp_path,
        cap=50,
        rng=random.Random(1),
        risk_scorer=scorer,
    )

    targets = select_targets("llm-risk", ctx)

    assert len(targets) == 2  # quota (2) == candidate count (2): both picked, no call needed
    assert scorer.calls is None


def test_llm_risk_falls_back_to_uniform_when_scorer_returns_none_for_one_file(
    tmp_path: Path,
) -> None:
    a = _write(tmp_path, "a.py", "1\n2\n3\n4\n5\n")
    b = _write(tmp_path, "b.py", "1\n2\n3\n4\n5\n")
    baseline = make_baseline({a: {1, 2, 3, 4, 5}, b: {1, 2, 3, 4, 5}})
    scorer = FakeRiskScorer(
        scores_by_file={
            a: None,
            b: {1: 100.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0},
        }
    )
    ctx = TargetingContext(
        baseline=baseline,
        module=make_module(),
        repo_root=tmp_path,
        cap=2,  # quota of 1 line per file
        rng=random.Random(1),
        risk_scorer=scorer,
    )

    targets = select_targets("llm-risk", ctx)

    assert {t.file for t in targets} == {Path("a.py"), Path("b.py")}
    b_target = next(t for t in targets if t.file == Path("b.py"))
    assert b_target.line == 1  # heavily-weighted line wins for the scored file


def test_llm_risk_preserves_file_level_fairness(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.py", "1\n2\n3\n4\n")
    b = _write(tmp_path, "b.py", "1\n2\n")
    c = _write(tmp_path, "c.py", "1\n2\n3\n")
    baseline = make_baseline({a: {1, 2, 3, 4}, b: {1, 2}, c: {1, 2, 3}})
    scorer = FakeRiskScorer(scores_by_file={a: {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}})
    ctx = TargetingContext(
        baseline=baseline,
        module=make_module(),
        repo_root=tmp_path,
        cap=3,
        rng=random.Random(1),
        risk_scorer=scorer,
    )

    targets = select_targets("llm-risk", ctx)

    files = [t.file for t in targets]
    assert sorted(files) == [Path("a.py"), Path("b.py"), Path("c.py")]
    assert len(targets) == 3
