"""Unit tests for coverage parsing and lcov path normalization."""

from __future__ import annotations

from pathlib import Path

import pytest

from cerebrum.baseline.coverage import (
    UnresolvedSourceWarning,
    parse_coverage,
)


def _make_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo_root = tmp_path
    module_root = repo_root / "backend"
    source = module_root / "routes" / "meals.js"
    source.parent.mkdir(parents=True)
    source.write_text("// source\n", encoding="utf-8")
    return repo_root, module_root, source


def _write_lcov(tmp_path: Path, sf: str) -> Path:
    lcov = tmp_path / "lcov.info"
    lcov.write_text(
        f"SF:{sf}\nDA:1,5\nDA:2,0\nDA:3,1\nend_of_record\n",
        encoding="utf-8",
    )
    return lcov


def test_lcov_covered_and_instrumented(tmp_path: Path) -> None:
    repo_root, module_root, source = _make_repo(tmp_path)
    lcov = _write_lcov(tmp_path, "routes/meals.js")
    data = parse_coverage("lcov", lcov, module_root, repo_root)
    key = source.resolve()
    assert data.covered == {key: {1, 3}}
    assert data.instrumented == {key: {1, 2, 3}}


@pytest.mark.parametrize("style", ["module", "repo", "absolute"])
def test_lcov_path_normalization(tmp_path: Path, style: str) -> None:
    repo_root, module_root, source = _make_repo(tmp_path)
    sf = {
        "module": "routes/meals.js",
        "repo": "backend/routes/meals.js",
        "absolute": str(source),
    }[style]
    lcov = _write_lcov(tmp_path, sf)
    data = parse_coverage("lcov", lcov, module_root, repo_root)
    assert set(data.covered) == {source.resolve()}


def test_lcov_unresolvable_source_warns(tmp_path: Path) -> None:
    repo_root, module_root, _ = _make_repo(tmp_path)
    lcov = _write_lcov(tmp_path, "nope/missing.js")
    with pytest.warns(UnresolvedSourceWarning):
        data = parse_coverage("lcov", lcov, module_root, repo_root)
    assert data.covered


@pytest.mark.parametrize("fmt", ["cobertura", "coverage.py", "json"])
def test_unsupported_format_raises(tmp_path: Path, fmt: str) -> None:
    artifact = tmp_path / "cov"
    artifact.write_text("", encoding="utf-8")
    with pytest.raises(NotImplementedError, match=fmt):
        parse_coverage(fmt, artifact, tmp_path, tmp_path)  # type: ignore[arg-type]
