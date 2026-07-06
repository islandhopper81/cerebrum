"""Configuration adapter: the portability contract between the engine and a target repo."""

from cerebrum.config.loader import ConfigError, load_config
from cerebrum.config.model import (
    Baseline,
    CerebrumConfig,
    Module,
    Mutation,
    Runtime,
    Targeting,
)

__all__ = [
    "Baseline",
    "CerebrumConfig",
    "ConfigError",
    "Module",
    "Mutation",
    "Runtime",
    "Targeting",
    "load_config",
]
