"""Baseline stage: establish a green, coverage-measured reference run."""

from cerebrum.baseline.coverage import CoverageData, parse_coverage
from cerebrum.baseline.models import BaselineResult, CoveredLineMap
from cerebrum.baseline.runner import BaselineError, run_baseline

__all__ = [
    "BaselineError",
    "BaselineResult",
    "CoverageData",
    "CoveredLineMap",
    "parse_coverage",
    "run_baseline",
]
