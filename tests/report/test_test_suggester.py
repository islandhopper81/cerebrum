"""Unit tests for the Claude-backed test suggester — the SDK client is stubbed out."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from cerebrum.report.survivors import SurvivorEntry
from cerebrum.report.test_suggester import TestSuggester, TestSuggesterError


@dataclass
class _Block:
    text: str


@dataclass
class _Response:
    content: list[_Block]


class _StubClient:
    """Captures the create() kwargs and returns a canned response."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.captured: dict[str, Any] = {}

        class _Messages:
            def create(inner: Any, **kwargs: Any) -> _Response:
                self.captured = kwargs
                return _Response(content=[_Block(text=self._text)])

        self.messages = _Messages()


def _entry() -> SurvivorEntry:
    return SurvivorEntry(
        file="a.py",
        line=5,
        diff="--- a/a.py\n+++ b/a.py\n@@ -5 +5 @@\n-x = 1\n+x = 2\n",
        mutation_type="arithmetic",
        severity="high",
        rationale="changed a constant",
        covering_tests="pytest",
        suggested_test=None,
        consecutive_runs=1,
    )


def _suggester(client: Any) -> TestSuggester:
    return TestSuggester(model="claude-sonnet-5", budget_usd=10, client=client)


def test_suggest_returns_stripped_text() -> None:
    suggester = _suggester(_StubClient("  def test_x():\n    assert x == 1\n  "))

    result = suggester.suggest(_entry())

    assert result == "def test_x():\n    assert x == 1"


def test_suggest_passes_configured_model_to_the_client() -> None:
    client = _StubClient("def test_x(): pass")
    _suggester(client).suggest(_entry())

    assert client.captured["model"] == "claude-sonnet-5"


def test_suggest_returns_none_on_empty_response() -> None:
    result = _suggester(_StubClient("   ")).suggest(_entry())
    assert result is None


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    suggester = TestSuggester(model="claude-sonnet-5", budget_usd=10, api_key=None)
    with pytest.raises(TestSuggesterError):
        suggester.suggest(_entry())


def test_budget_guard_raises_when_estimate_exceeds_budget() -> None:
    suggester = TestSuggester(
        model="claude-sonnet-5", budget_usd=0.0000001, client=_StubClient("x")
    )
    with pytest.raises(TestSuggesterError):
        suggester.suggest(_entry())
