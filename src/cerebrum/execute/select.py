"""Pick one target line to mutate.

Deliberately minimal for #3: an explicit ``file``/``line`` override, else the
first covered line in sorted-path order. This exists only to feed the lifecycle a
deterministic target so the mechanical loop can be proven trustworthy. The smart
strategies (``coverage`` ranking, ``changed``, ``llm-risk``, ``all``) are #5 and
supersede this selector.
"""

from __future__ import annotations

from pathlib import Path

from cerebrum.baseline.models import BaselineResult
from cerebrum.config.model import Module
from cerebrum.generate.operator import MutationTarget


def select_target(
    baseline: BaselineResult,
    module: Module,
    repo_root: Path,
    *,
    file: str | None = None,
    line: int | None = None,
) -> MutationTarget | None:
    """Return a target, or ``None`` when nothing can be selected.

    Whether the chosen line is actually covered is decided by the lifecycle
    (an explicit override may point at an uncovered line → ``NO_COVERAGE``).
    """
    if (file is None) != (line is None):
        raise ValueError("file and line must be given together, or neither")

    repo_root = repo_root.resolve()

    if file is not None and line is not None:
        abs_path = Path(file)
        if not abs_path.is_absolute():
            abs_path = repo_root / file
        return _build_target(abs_path.resolve(), line, repo_root, module.language)

    for path in sorted(baseline.covered_lines):
        lines = baseline.covered_lines[path]
        if lines:
            return _build_target(path, min(lines), repo_root, module.language)
    return None


def _build_target(
    abs_path: Path, line: int, repo_root: Path, language: str
) -> MutationTarget:
    rel = abs_path.relative_to(repo_root)
    source_text = abs_path.read_text(encoding="utf-8") if abs_path.exists() else ""
    return MutationTarget(
        file=rel, line=line, source_text=source_text, language=language
    )
