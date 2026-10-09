"""Idle states: awake -> clock (screen saver) -> off, and back to awake on any key.

After `clock_minutes` without a press the deck shows a large clock; after `sleep_minutes` the keys
go black, unless an alert is showing: then the clock and its alert banner stay up, and the keys go
black once the alert clears (and back to the clock if another one appears). Any key wakes it, and
the waking press is a no-op: both its down and its up are swallowed, so it never reaches the
gestures. 0 disables a stage.
"""

from datetime import datetime, timedelta
from enum import StrEnum


class Idle(StrEnum):
    AWAKE = "awake"
    CLOCK = "clock"
    OFF = "off"


def brightness_for(state: Idle, configured: int) -> int:
    """The backlight for an idle state: off really means off (0). Black key images alone leave the
    LCD backlight lit, a visible grey glow (user report)."""
    return 0 if state == Idle.OFF else configured


class IdleTimer:
    def __init__(self, clock_minutes: int, sleep_minutes: int, now: datetime) -> None:
        self.clock_after = timedelta(minutes=clock_minutes)
        self.sleep_after = timedelta(minutes=sleep_minutes)
        self.last_press = now
        self.state = Idle.AWAKE
        self._swallow: set[int] = set()  # keys whose waking press we are still swallowing

    def key(self, index: int, pressed: bool, now: datetime) -> bool:
        """A key event. Returns True if it should reach the deck, False if it was a wake (swallowed)."""
        self.last_press = now
        if pressed and self.state != Idle.AWAKE:
            self.state = Idle.AWAKE
            self._swallow.add(index)
            return False
        if not pressed and index in self._swallow:
            self._swallow.discard(index)
            return False
        return True

    def tick(self, now: datetime, alerting: bool = False) -> Idle | None:
        """Advance on time. Returns the new state when it changed (the caller redraws), else None.
        `alerting` holds the clock past sleep time so its alert banner stays visible."""
        idle = now - self.last_press
        target = Idle.AWAKE
        if self.clock_after > timedelta(0) and idle >= self.clock_after:
            target = Idle.CLOCK
        if self.sleep_after > timedelta(0) and idle >= self.sleep_after:
            target = Idle.OFF
            if alerting and self.clock_after > timedelta(0):
                target = Idle.CLOCK
        # Idle time only grows until a press, so the target never moves back to AWAKE here; only
        # key() wakes the deck. An alert can move it from OFF back to CLOCK.
        if target == self.state or target == Idle.AWAKE:
            return None
        self.state = target
        return target
