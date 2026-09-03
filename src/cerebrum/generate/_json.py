"""Shared JSON-extraction helper for LLM response parsing."""

from __future__ import annotations


def extract_json(text: str) -> str | None:
    """Pull the first ``{...}`` object out of a model response, tolerating code
    fences and surrounding prose."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    return text[start : end + 1]
