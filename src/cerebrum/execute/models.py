"""Engine-internal outputs of the EXECUTE stage.

:class:`MutantRecord` is the hard API REPORTING (#6) consumes from
``.cerebrum/mutants.jsonl``. ``status`` is the fixed five-value enum from the
README's "Mutant outcomes" table — do not extend it without updating reporting.
``file`` is stored repo-root-relative so records are portable across machines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MutantStatus = Literal["KILLED", "SURVIVED", "TIMEOUT", "BUILD_ERROR", "NO_COVERAGE"]


@dataclass(frozen=True)
class MutantRecord:
    file: str
    line: int
    diff: str
    mutation_type: str
    status: MutantStatus
    covering_tests: str
    rationale: str
    duration_seconds: float
    severity: str = ""
