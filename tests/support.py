"""Importable test helpers (kept out of conftest so tests can import them directly)."""

from __future__ import annotations

from typing import Any


def base_config() -> dict[str, Any]:
    """A minimal, valid config mapping. Tests deep-copy and mutate this."""
    return {
        "version": 1,
        "project": "Demo",
        "modules": [
            {
                "name": "backend",
                "root": "backend",
                "language": "javascript",
                "install": "npm ci",
                "test": "npm test",
                "source": ["**/*.js"],
            }
        ],
        "mutation": {"model": "claude-sonnet-5", "budget_usd": 10},
    }
