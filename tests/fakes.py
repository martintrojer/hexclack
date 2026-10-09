"""Test doubles: a scriptable device and a manual clock."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


@dataclass
class FakeDevice:
    """present: the deck enumerates. healthy: health checks pass. open_fails: open() raises."""

    serial: str = "BL46L2B01413"
    present: bool = True
    healthy: bool = True
    open_fails: bool = False
    firmware: str = "2.01.002"
    opened: int = 0
    resets: int = 0
    calls: list[str] = field(default_factory=list)
    _open: bool = False

    def enumerate_serials(self) -> list[str]:
        self.calls.append("enumerate")
        return [self.serial] if self.present else []

    def open(self) -> str:
        self.calls.append("open")
        if self.open_fails:
            raise OSError("Could not open HID device.")
        self.opened += 1
        self._open = True
        return self.serial

    def close(self) -> None:
        self.calls.append("close")
        self._open = False

    def reset(self) -> None:
        self.calls.append("reset")
        self.resets += 1

    def is_open(self) -> bool:
        self.calls.append("is_open")
        return self._open

    def reader_alive(self) -> bool:
        self.calls.append("reader_alive")
        return self._open and self.healthy

    def firmware_version(self) -> str:
        self.calls.append("firmware_version")
        return self.firmware if self.healthy else ""
