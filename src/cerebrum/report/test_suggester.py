"""Claude-backed test suggestion for a survivor.

Given a survivor's diff, rationale, and covering-test command, asks Claude to
write a test snippet that would have caught the mutation — the second half of
"survivors are the deliverable a developer acts on." Mirrors
:class:`cerebrum.generate.llm.LLMOperator`'s pattern exactly: lazy ``anthropic``
import, an injectable client for tests, the same budget-guard shape, and a
non-fatal ``None`` return on failure — a survivor without a suggested test is
still reported, just with that one field unfilled.
"""

from __future__ import annotations

import os
from typing import Any

from cerebrum.report.survivors import SurvivorEntry

_INPUT_USD_PER_TOKEN = 3.0 / 1_000_000
_OUTPUT_USD_PER_TOKEN = 15.0 / 1_000_000


class TestSuggesterError(Exception):
    """Raised for setup/precondition failures — missing key, exceeded budget."""

    __test__ = False  # not a pytest test class despite the name


class TestSuggester:
    __test__ = False  # not a pytest test class despite the name

    def __init__(
        self,
        model: str,
        budget_usd: float,
        *,
        api_key: str | None = None,
        client: Any = None,
        max_tokens: int = 1024,
    ) -> None:
        self._model = model
        self._budget_usd = budget_usd
        self._api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
        self._client = client
        self._max_tokens = max_tokens

    def suggest(self, entry: SurvivorEntry) -> str | None:
        prompt = self._build_prompt(entry)
        self._guard_budget(prompt)
        client = self._resolve_client()
        try:
            text = self._call(client, prompt)
        except Exception:
            return None
        return text.strip() or None

    def _guard_budget(self, prompt: str) -> None:
        estimated = (
            len(prompt) / 4 * _INPUT_USD_PER_TOKEN
            + self._max_tokens * _OUTPUT_USD_PER_TOKEN
        )
        if estimated > self._budget_usd:
            raise TestSuggesterError(
                f"estimated call cost ${estimated:.4f} exceeds budget ${self._budget_usd:.2f}"
            )

    def _resolve_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._api_key is None:
            raise TestSuggesterError(
                "ANTHROPIC_API_KEY is not set; cannot suggest tests"
            )
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

    def _build_prompt(self, entry: SurvivorEntry) -> str:
        return (
            "A mutation-testing tool inserted a bug into this codebase and the "
            "test suite failed to catch it. Write a test snippet, in the style "
            "implied by the test command below, that would have caught this "
            "specific bug. Respond with ONLY the test code, no prose, no code "
            "fences.\n\n"
            f"File: {entry.file}:{entry.line}\n"
            f"Mutation type: {entry.mutation_type}\n"
            f"What changed: {entry.rationale}\n"
            f"Test command: {entry.covering_tests}\n\n"
            "Diff of the bug that survived:\n"
            "```\n"
            f"{entry.diff}"
            "```\n"
        )
