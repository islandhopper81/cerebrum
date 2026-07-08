"""Tests for the `cerebrum` CLI entrypoint itself, independent of any subcommand."""

from __future__ import annotations

import sys

import pytest

from cerebrum.cli import main


def test_main_reconfigures_stdout_and_stderr_to_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows consoles default to a legacy codepage (e.g. cp1252) that can't
    encode characters like the arrows `run`/`report` print in their output,
    crashing after mutation testing has already completed. Reconfiguring to
    utf-8 up front avoids that regardless of the invoking codepage/locale."""
    calls: list[tuple[str, str]] = []

    class FakeStream:
        def reconfigure(self, *, encoding: str, errors: str) -> None:
            calls.append((encoding, errors))

    monkeypatch.setattr(sys, "stdout", FakeStream())
    monkeypatch.setattr(sys, "stderr", FakeStream())

    with pytest.raises(SystemExit):
        main(["--help"])

    assert calls == [("utf-8", "replace"), ("utf-8", "replace")]


def test_main_does_not_crash_if_stream_lacks_reconfigure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BareStream:
        pass

    monkeypatch.setattr(sys, "stdout", BareStream())
    monkeypatch.setattr(sys, "stderr", BareStream())

    with pytest.raises(SystemExit):
        main(["--help"])
