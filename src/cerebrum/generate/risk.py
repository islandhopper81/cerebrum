"""Claude-backed risk scorer — ranks a file's candidate lines by how consequential
a missed bug there would be, for the ``llm-risk`` targeting strategy.

Mirrors :class:`~cerebrum.generate.llm.LLMOperator`'s constructor shape and its
lazy-anthropic-import / client-resolution pattern, duplicated rather than shared
(see #39's Out of Scope: only two call sites so far, too early to abstract). A
network or parse failure yields ``None`` — "no risk scores" — which targeting
treats as a non-fatal per-file fallback to uniform weighting; only a missing API
key or a blown budget raises.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cerebrum.generate._json import extract_json

# Rough per-token USD rates used only for the pre-call budget guard. Real
# accounting lands in REPORTING (#6); at one file this rarely trips.
_INPUT_USD_PER_TOKEN = 3.0 / 1_000_000
_OUTPUT_USD_PER_TOKEN = 15.0 / 1_000_000


class LLMRiskScorerError(Exception):
    """Raised for setup/precondition failures — missing key, exceeded budget."""


class LLMRiskScorer:
    def __init__(
        self,
        model: str,
        budget_usd: float,
        *,
        api_key: str | None = None,
        client: Any = None,
        max_tokens: int = 2048,
    ) -> None:
        self._model = model
        self._budget_usd = budget_usd
        self._api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
        self._client = client
        self._max_tokens = max_tokens

    def score(
        self, file: Path, source_text: str, candidate_lines: list[int]
    ) -> dict[int, float] | None:
        prompt = self._build_prompt(file, source_text, candidate_lines)
        self._guard_budget(prompt)
        client = self._resolve_client()
        try:
            text = self._call(client, prompt)
        except Exception:
            return None
        return self._parse(text, candidate_lines)

    def _guard_budget(self, prompt: str) -> None:
        estimated = (
            len(prompt) / 4 * _INPUT_USD_PER_TOKEN + self._max_tokens * _OUTPUT_USD_PER_TOKEN
        )
        if estimated > self._budget_usd:
            raise LLMRiskScorerError(
                f"estimated call cost ${estimated:.4f} exceeds budget ${self._budget_usd:.2f}"
            )

    def _resolve_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._api_key is None:
            raise LLMRiskScorerError("ANTHROPIC_API_KEY is not set; cannot score risk")
        import anthropic

        self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def _call(self, client: Any, prompt: str) -> str:
        response = client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [
            str(getattr(block, "text", ""))
            for block in response.content
            if getattr(block, "text", None) is not None
        ]
        return "".join(parts)

    def _build_prompt(self, file: Path, source_text: str, candidate_lines: list[int]) -> str:
        return (
            "You are assessing mutation-testing risk. For each candidate line "
            "below, estimate how consequential an undetected bug there would be "
            "if it shipped to production — financial/security-sensitive logic, "
            "complex conditionals, and edge-case handling score high; trivial or "
            "low-stakes code (logging, simple getters) scores low.\n\n"
            f"File (repo-relative): {file.as_posix()}\n"
            f"Candidate lines: {candidate_lines}\n\n"
            "Source:\n"
            "```\n"
            f"{source_text}"
            "```\n\n"
            "Respond with ONLY a JSON object, no prose, mapping each candidate "
            'line number (as a string key) to a risk score in [0.0, 1.0], e.g. '
            '{"12": 0.8, "47": 0.1}.'
        )

    def _parse(self, text: str, candidate_lines: list[int]) -> dict[int, float] | None:
        payload = extract_json(text)
        if payload is None:
            return None
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None

        scores: dict[int, float] = {}
        for key, value in data.items():
            try:
                line = int(key)
            except (TypeError, ValueError):
                continue
            if line not in candidate_lines:
                continue
            if not isinstance(value, int | float) or isinstance(value, bool):
                continue
            scores[line] = max(0.0, min(1.0, float(value)))

        for line in candidate_lines:
            scores.setdefault(line, 1.0)
        return scores
