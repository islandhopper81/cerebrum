"""REPORT stage: score, survivor report, suggested tests, trend across runs."""

from cerebrum.report.history import init_db, record_run, recurring_survivors, trend
from cerebrum.report.models import RunSummary
from cerebrum.report.score import SEVERITY_WEIGHT, average_survivor_severity, compute_score
from cerebrum.report.survivors import SurvivorEntry, build_survivor_report
from cerebrum.report.test_suggester import TestSuggester, TestSuggesterError

__all__ = [
    "SEVERITY_WEIGHT",
    "RunSummary",
    "SurvivorEntry",
    "TestSuggester",
    "TestSuggesterError",
    "average_survivor_severity",
    "build_survivor_report",
    "compute_score",
    "init_db",
    "record_run",
    "recurring_survivors",
    "trend",
]
