"""Load and validate ``cerebrum.yaml`` into a :class:`CerebrumConfig`."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from cerebrum.config.model import CerebrumConfig

DEFAULT_CONFIG_NAME = "cerebrum.yaml"


class ConfigError(Exception):
    """Raised when a config file is missing, unparseable, or invalid.

    Messages name the offending field/module and the file path so the problem is
    fixable without reading a traceback.
    """


def load_config(path: str | Path) -> CerebrumConfig:
    """Parse and validate a ``cerebrum.yaml`` file.

    Raises :class:`ConfigError` (never a bare ``ValidationError`` or ``YAMLError``)
    with a message that names the file and the specific problem.
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except OSError as exc:  # pragma: no cover - unusual filesystem errors
        raise ConfigError(f"could not read config file {path}: {exc}") from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc

    if data is None:
        raise ConfigError(f"{path}: config is empty")
    if not isinstance(data, dict):
        raise ConfigError(
            f"{path}: top-level config must be a mapping, got {type(data).__name__}"
        )

    try:
        return CerebrumConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(path, exc)) from exc


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    lines = [f"{path}: invalid config ({exc.error_count()} error(s)):"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)
