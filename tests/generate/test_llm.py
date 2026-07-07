"""Unit tests for the Claude-backed operator — the SDK client is stubbed out."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from cerebrum.generate.llm import LLMOperator, LLMOperatorError
from cerebrum.generate.operator import MutationTarget


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


def _target() -> MutationTarget:
    return MutationTarget(
        file=Path("app.py"), line=1, source_text="x = 1\n", language="python"
    )


def _operator(client: Any) -> LLMOperator:
    return LLMOperator(model="claude-sonnet-5", budget_usd=10, client=client)


def test_parses_json_response_into_proposal() -> None:
    payload = json.dumps(
        {
            "diff": "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n",
            "mutation_type": "arithmetic",
            "rationale": "changed a constant",
            "equivalent": False,
            "severity": "high",
        }
    )
    operator = _operator(_StubClient(f"Here you go:\n```json\n{payload}\n```"))

    proposal = operator.propose(_target())

    assert proposal is not None
    assert proposal.mutation_type == "arithmetic"
    assert proposal.rationale == "changed a constant"
    assert "+x = 2" in proposal.diff
    assert proposal.severity == "high"


def test_unknown_severity_falls_back_to_medium() -> None:
    client = _StubClient(
        json.dumps(
            {
                "diff": "--- a/app.py\n+++ b/app.py\n",
                "mutation_type": "logic",
                "severity": "catastrophic",
            }
        )
    )
    proposal = _operator(client).propose(_target())

    assert proposal is not None
    assert proposal.severity == "medium"


def test_missing_severity_falls_back_to_medium() -> None:
    client = _StubClient(
        json.dumps({"diff": "--- a/app.py\n+++ b/app.py\n", "mutation_type": "logic"})
    )
    proposal = _operator(client).propose(_target())

    assert proposal is not None
    assert proposal.severity == "medium"


def test_passes_configured_model_to_the_client() -> None:
    client = _StubClient(
        json.dumps({"diff": "--- a/app.py\n+++ b/app.py\n", "mutation_type": "logic"})
    )
    _operator(client).propose(_target())

    assert client.captured["model"] == "claude-sonnet-5"


def test_unknown_mutation_type_falls_back_to_other() -> None:
    client = _StubClient(
        json.dumps({"diff": "--- a/app.py\n+++ b/app.py\n", "mutation_type": "nonsense"})
    )
    proposal = _operator(client).propose(_target())

    assert proposal is not None
    assert proposal.mutation_type == "other"


def test_malformed_response_returns_none() -> None:
    proposal = _operator(_StubClient("not json at all")).propose(_target())
    assert proposal is None


def test_response_missing_diff_returns_none() -> None:
    client = _StubClient(json.dumps({"mutation_type": "logic", "rationale": "x"}))
    assert _operator(client).propose(_target()) is None


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    operator = LLMOperator(model="claude-sonnet-5", budget_usd=10, api_key=None)
    with pytest.raises(LLMOperatorError):
        operator.propose(_target())


def test_budget_guard_raises_when_estimate_exceeds_budget() -> None:
    operator = LLMOperator(
        model="claude-sonnet-5", budget_usd=0.0000001, client=_StubClient("{}")
    )
    with pytest.raises(LLMOperatorError):
        operator.propose(_target())
