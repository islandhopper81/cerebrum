"""Run a shell command and capture its result.

Used by the baseline stage (and later the per-mutant EXECUTE stage) to invoke a
target repo's ``install``/``test`` commands. Commands come from the trusted,
committed ``cerebrum.yaml``, so they run through the shell (``shell=True``) to
allow shell operators and to let Windows resolve executables such as ``npm`` to
``npm.cmd``. Shell injection is therefore out of the threat model — the config
author already controls the machine the engine runs on.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

TIMEOUT_EXIT_CODE = 124


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


def run_command(
    command: str,
    cwd: Path,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
) -> CommandResult:
    """Run ``command`` in ``cwd`` and return its captured result.

    A timeout does not raise: the returned :class:`CommandResult` carries
    :data:`TIMEOUT_EXIT_CODE` so callers branch on exit code uniformly.
    """
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=command,
            exit_code=TIMEOUT_EXIT_CODE,
            stdout=_decode(exc.stdout),
            stderr=_decode(exc.stderr),
            duration_seconds=time.perf_counter() - start,
        )
    return CommandResult(
        command=command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=time.perf_counter() - start,
    )


def _decode(data: str | bytes | None) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data
