"""Unit tests for minimal target selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from cerebrum.execute.select import build_targets, select_target
from tests.support import make_baseline, make_module


def _write(repo: Path, rel: str, text: str) -> Path:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path.resolve()


def test_first_covered_line_is_selected(tmp_path: Path) -> None:
    src = _write(tmp_path, "pkg/mod.py", "a\nb\nc\nd\ne\n")
    baseline = make_baseline({src: {5, 3}})

    target = select_target(baseline, make_module(), tmp_path)

    assert target is not None
    assert target.file == Path("pkg/mod.py")
    assert target.line == 3
    assert target.source_text == "a\nb\nc\nd\ne\n"
    assert target.language == "python"


def test_explicit_file_and_line_override(tmp_path: Path) -> None:
    src = _write(tmp_path, "pkg/mod.py", "a\nb\nc\n")
    baseline = make_baseline({src: {1}})

    target = select_target(baseline, make_module(), tmp_path, file="pkg/mod.py", line=2)

    assert target is not None
    assert target.file == Path("pkg/mod.py")
    assert target.line == 2


def test_explicit_uncovered_line_still_returns_target(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", "a\nb\n")
    baseline = make_baseline({})

    target = select_target(baseline, make_module(), tmp_path, file="pkg/mod.py", line=99)

    assert target is not None
    assert target.line == 99


def test_no_covered_lines_returns_none(tmp_path: Path) -> None:
    baseline = make_baseline({})
    assert select_target(baseline, make_module(), tmp_path) is None


def test_file_without_line_is_an_error(tmp_path: Path) -> None:
    baseline = make_baseline({})
    with pytest.raises(ValueError):
        select_target(baseline, make_module(), tmp_path, file="pkg/mod.py")


def test_build_targets_yields_one_target_per_sorted_line(tmp_path: Path) -> None:
    src = _write(tmp_path, "pkg/mod.py", "a\nb\nc\nd\ne\n")

    targets = build_targets(src, {4, 2}, tmp_path, "python")

    assert [t.line for t in targets] == [2, 4]
    assert all(t.file == Path("pkg/mod.py") for t in targets)
    assert all(t.source_text == "a\nb\nc\nd\ne\n" for t in targets)
