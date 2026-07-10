"""Parse a module's coverage artifact into normalized line maps.

Only ``lcov`` is implemented — the sole format M1's target (FeedTheFamily)
emits. The other schema-allowed formats raise :class:`NotImplementedError` so
the contract is explicit and each follow-up is a drop-in.

``covered`` holds lines that actually executed; ``instrumented`` holds every
line the tool tracked (hit or not). ``instrumented - covered`` per file is the
executable-but-untested set, the raw material for ``NO_COVERAGE`` reporting (#5).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

from cerebrum.baseline.models import CoveredLineMap
from cerebrum.config.model import CoverageFormat


class UnresolvedSourceWarning(UserWarning):
    """Emitted when a coverage record names a file that is not found on disk."""


@dataclass(frozen=True)
class CoverageData:
    covered: CoveredLineMap
    instrumented: CoveredLineMap


def parse_coverage(
    fmt: CoverageFormat,
    path: Path,
    module_root: Path,
    repo_root: Path,
) -> CoverageData:
    if fmt == "lcov":
        return _parse_lcov(path, module_root, repo_root)
    raise NotImplementedError(
        f"coverage_format '{fmt}' not yet supported (M1 supports lcov)"
    )


def _parse_lcov(path: Path, module_root: Path, repo_root: Path) -> CoverageData:
    covered: CoveredLineMap = {}
    instrumented: CoveredLineMap = {}
    current: Path | None = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("SF:"):
            current = _resolve_source(line[3:], module_root, repo_root)
            instrumented.setdefault(current, set())
        elif line.startswith("DA:") and current is not None:
            number, hits = _parse_da(line[3:])
            if number is None:
                continue
            instrumented.setdefault(current, set()).add(number)
            if hits > 0:
                covered.setdefault(current, set()).add(number)
        elif line == "end_of_record":
            current = None

    return CoverageData(covered=covered, instrumented=instrumented)


def _parse_da(payload: str) -> tuple[int | None, int]:
    parts = payload.split(",")
    if len(parts) < 2:
        return None, 0
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, 0


def _resolve_source(sf: str, module_root: Path, repo_root: Path) -> Path:
    """Resolve an lcov ``SF`` path to an absolute on-disk path.

    The base is not standardized across coverage tools, so try the file as
    written (if absolute), then relative to the module root, then the repo root,
    and keep whichever exists. If none exist, fall back to the module-root
    interpretation and warn — a coverage entry we cannot locate is suspicious
    but not fatal.
    """
    raw = Path(sf)
    candidates = [raw] if raw.is_absolute() else [module_root / sf, repo_root / sf]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    warnings.warn(
        f"coverage names a source file that could not be located on disk: {sf}",
        UnresolvedSourceWarning,
        stacklevel=2,
    )
    fallback = raw if raw.is_absolute() else module_root / sf
    return fallback.resolve()
