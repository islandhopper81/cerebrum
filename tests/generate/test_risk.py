"""Unit tests for the Claude-backed risk scorer — the SDK client is stubbed out."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from cerebrum.generate.risk import LLMRiskScorer, LLMRiskScorerError


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


def _scorer(client: Any) -> LLMRiskScorer:
    return LLMRiskScorer(model="claude-sonnet-5", budget_usd=10, client=client)


def test_well_formed_json_response_returns_score_dict() -> None:
    payload = json.dumps({"1": 0.9, "2": 0.1})
    scorer = _scorer(_StubClient(f"Here you go:\n```json\n{payload}\n```"))

    scores = scorer.score(Path("app.py"), "x = 1\ny = 2\n", [1, 2])

    assert scores == {1: 0.9, 2: 0.1}


def test_out_of_range_score_is_clamped() -> None:
    client = _StubClient(json.dumps({"1": 5.0, "2": -3.0}))
    scores = _scorer(client).score(Path("app.py"), "x = 1\ny = 2\n", [1, 2])

    assert scores == {1: 1.0, 2: 0.0}


def test_missing_requested_line_defaults_to_one() -> None:
    client = _StubClient(json.dumps({"1": 0.3}))
    scores = _scorer(client).score(Path("app.py"), "x = 1\ny = 2\n", [1, 2])

    assert scores == {1: 0.3, 2: 1.0}


def test_malformed_response_returns_none() -> None:
    scores = _scorer(_StubClient("not json at all")).score(
        Path("app.py"), "x = 1\n", [1]
    )
    assert scores is None


def test_non_dict_response_returns_none() -> None:
    scores = _scorer(_StubClient(json.dumps([1, 2, 3]))).score(
        Path("app.py"), "x = 1\n", [1]
    )
    assert scores is None


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    scorer = LLMRiskScorer(model="claude-sonnet-5", budget_usd=10, api_key=None)
    with pytest.raises(LLMRiskScorerError):
        scorer.score(Path("app.py"), "x = 1\n", [1])


def test_budget_guard_raises_when_estimate_exceeds_budget() -> None:
    scorer = LLMRiskScorer(
        model="claude-sonnet-5", budget_usd=0.0000001, client=_StubClient("{}")
    )
    with pytest.raises(LLMRiskScorerError):
        scorer.score(Path("app.py"), "x = 1\n", [1])
