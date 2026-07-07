"""Claude-backed mutation operator — the real "insert one bug" step.

Reproduces experiment2's second prompt: given a target line, ask the model to
inject exactly one small, realistic bug and return it as a unified diff plus
metadata. The ``anthropic`` SDK is imported lazily so the rest of the engine (and
the whole test suite, which uses a fake operator) never needs it installed. A
network or parse failure yields ``None`` — "no mutant produced" — which the
lifecycle treats as a non-fatal skip; only a missing API key or a blown budget
raises.
"""

from __future__ import annotations

import json
import os
from typing import Any, cast, get_args

from cerebrum.generate.operator import MutantProposal, MutationTarget, MutationType, Severity

_MUTATION_TYPES = frozenset(get_args(MutationType))
_SEVERITIES = frozenset(get_args(Severity))

# Rough per-token USD rates used only for the pre-call budget guard. Real
# accounting lands in REPORTING (#6); at one mutant this never trips.
_INPUT_USD_PER_TOKEN = 3.0 / 1_000_000
_OUTPUT_USD_PER_TOKEN = 15.0 / 1_000_000


class LLMOperatorError(Exception):
    """Raised for setup/precondition failures — missing key, exceeded budget."""


class LLMOperator:
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

    def propose(self, target: MutationTarget) -> MutantProposal | None:
        prompt = self._build_prompt(target)
        self._guard_budget(prompt)
        client = self._resolve_client()
        try:
            text = self._call(client, prompt)
        except Exception:
            return None
        return self._parse(text)

    def _guard_budget(self, prompt: str) -> None:
        estimated = (
            len(prompt) / 4 * _INPUT_USD_PER_TOKEN
            + self._max_tokens * _OUTPUT_USD_PER_TOKEN
        )
        if estimated > self._budget_usd:
            raise LLMOperatorError(
                f"estimated call cost ${estimated:.4f} exceeds budget ${self._budget_usd:.2f}"
            )

    def _resolve_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._api_key is None:
            raise LLMOperatorError(
                "ANTHROPIC_API_KEY is not set; cannot generate mutants"
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

    def _build_prompt(self, target: MutationTarget) -> str:
        return (
            "You are a mutation-testing operator. Insert exactly ONE small, "
            "realistic bug into the code below — the kind of mistake a developer "
            "would plausibly make (an off-by-one, a flipped condition, a wrong "
            "operator, a dropped edge case). Change as little as possible and do "
            "not reformat.\n\n"
            f"Language: {target.language}\n"
            f"File (repo-relative): {target.file}\n"
            f"Focus on line {target.line}.\n\n"
            "Source:\n"
            "```\n"
            f"{target.source_text}"
            "```\n\n"
            "Respond with ONLY a JSON object, no prose, of the form:\n"
            '{"diff": "<unified diff>", "mutation_type": "<type>", '
            '"rationale": "<one sentence>", "equivalent": false, "severity": "<severity>"}\n\n'
            f"where mutation_type is one of {sorted(_MUTATION_TYPES)}, the diff is a "
            f"unified diff addressing the file as a/{target.file} and b/{target.file} "
            "(appliable with `git apply`), equivalent is true only if you could "
            f"not produce a behaviour-changing bug, and severity is one of "
            f"{sorted(_SEVERITIES)}, reflecting how consequential this bug would be "
            "if it shipped to production."
        )

    def _parse(self, text: str) -> MutantProposal | None:
        payload = _extract_json(text)
        if payload is None:
            return None
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        diff = data.get("diff")
        if not isinstance(diff, str) or not diff.strip():
            return None
        raw_type = data.get("mutation_type")
        mutation_type: MutationType = (
            cast(MutationType, raw_type) if raw_type in _MUTATION_TYPES else "other"
        )
        rationale = data.get("rationale")
        raw_severity = data.get("severity")
        severity: Severity = (
            cast(Severity, raw_severity) if raw_severity in _SEVERITIES else "medium"
        )
        return MutantProposal(
            diff=diff,
            mutation_type=mutation_type,
            rationale=rationale if isinstance(rationale, str) else "",
            equivalent=bool(data.get("equivalent", False)),
            severity=severity,
        )


def _extract_json(text: str) -> str | None:
    """Pull the first ``{...}`` object out of a model response, tolerating code
    fences and surrounding prose."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    return text[start : end + 1]
