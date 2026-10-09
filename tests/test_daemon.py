"""One bad poll must not stop every later poll: the deck's live keys would freeze with no error."""

import logging

import pytest

from hexclack.daemon import guarded


def test_guarded_logs_and_swallows(caplog: pytest.LogCaptureFixture) -> None:
    def boom() -> None:
        raise ValueError("torn")

    with caplog.at_level(logging.ERROR, logger="hexclack.daemon"):
        guarded("pihole server:8000", boom)  # must not raise
    assert "pihole server:8000 failed" in caplog.text
