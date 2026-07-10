"""Engine-internal outputs of the baseline stage.

These types are the hard API that TARGETING (#3), EXECUTE (#4), and REPORTING
(#5) import — analogous to ``CerebrumConfig`` for the config layer. Line-number
sets are 1-based; map keys are absolute, resolved source paths so they line up
with :meth:`cerebrum.config.model.Module.resolve_sources`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cerebrum.exec.command import CommandResult

CoveredLineMap = dict[Path, set[int]]


@dataclass(frozen=True)
class BaselineResult:
    module_name: str
    passed: bool
    test_duration_seconds: float
    covered_lines: CoveredLineMap
    instrumented_lines: CoveredLineMap
    install_result: CommandResult
    test_result: CommandResult
