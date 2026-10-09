"""Device state machine, health checks and the hung-call rules (docs/design.md section 4).

This module is pure logic: it never calls hidapi or sleeps. The device-owner thread calls `tick()`
on a schedule and runs the commands it gets back; a separate watchdog thread calls `check_hang()`
every second with the owner's heartbeat. Time, the device, exit and notification are injected,
so tests drive every transition without hardware.
"""

import contextlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

STATE_FILE = Path.home() / "Library/Application Support/hexclack/state.json"

HANG_EXIT = 70
HANG_WINDOW = timedelta(minutes=10)
NOTIFY_EVERY = timedelta(hours=6)
FAILS_TO_REOPEN = 3
REOPEN_CYCLES_TO_WEDGE = 3
REOPEN_BACKOFF_S = (1, 2, 4, 8)
WEDGED_RETRY = timedelta(seconds=60)
REPLUG_MESSAGE = "Stream Deck is not responding. Unplug it, wait 10 seconds, and plug it back in."


class State(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    OPEN = "OPEN"
    HEALTHY = "HEALTHY"
    SUSPECT = "SUSPECT"
    REOPENING = "REOPENING"
    WEDGED = "WEDGED"


class DeviceIO(Protocol):
    """What the watchdog needs from the device. The real one wraps streamdeck; tests use a fake."""

    def enumerate_serials(self) -> list[str]: ...
    def open(self) -> str: ...  # returns the serial
    def close(self) -> None: ...
    def reset(self) -> None: ...
    def is_open(self) -> bool: ...
    def reader_alive(self) -> bool: ...
    def firmware_version(self) -> str: ...


@dataclass
class Persisted:
    """state.json. Survives process restarts so the hang rules hold across launchd respawns."""

    state: str = State.DISCONNECTED
    notified_at: str | None = None
    hang_exits: int = 0
    last_exit: str | None = None
    left_wedged_since_notify: bool = True


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat()


def _parse(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def load_state(path: Path) -> Persisted:
    try:
        raw = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return Persisted()
    known = {k: v for k, v in raw.items() if k in Persisted.__dataclass_fields__}
    return Persisted(**known)


def save_state(path: Path, state: Persisted) -> None:
    """Write atomically: a half-written state.json would lose hang_exits across a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(state), sort_keys=True))
    os.replace(tmp, path)


class Watchdog:
    def __init__(
        self,
        device: DeviceIO,
        clock: Callable[[], datetime],
        exit_fn: Callable[[int], None],
        notify_fn: Callable[[str], None],
        state_file: Path = STATE_FILE,
        health_timeout_s: float = 2,
        use_reset: bool = True,
    ) -> None:
        self.device = device
        self.clock = clock
        self.exit_fn = exit_fn
        self.notify_fn = notify_fn
        self.state_file = state_file
        self.health_timeout = timedelta(seconds=health_timeout_s)
        self.use_reset = use_reset  # spike s09 decides whether reset() is part of a reopen
        self.persisted = load_state(state_file)
        self.state = State.DISCONNECTED
        self.serial: str | None = None
        self.fails = 0
        self.reopen_cycles = 0
        self.next_attempt: datetime | None = None
        self.wedged_from_startup = False
        self.accepting_draws = True
        self.suspended = False
        self._startup()

    # -- startup and persistence -------------------------------------------------------------

    def _startup(self) -> None:
        now = self.clock()
        last_exit = _parse(self.persisted.last_exit)
        if last_exit and now - last_exit < HANG_WINDOW and self.persisted.hang_exits >= 2:
            # Repeated hangs: opening the device again would hang again. Wait for a replug.
            self.wedged_from_startup = True
            serials = self.device.enumerate_serials()
            self.serial = serials[0] if serials else None
            self._enter_wedged()
        else:
            self._set(State.DISCONNECTED)

    def _save(self) -> None:
        self.persisted.state = self.state
        save_state(self.state_file, self.persisted)

    def _set(self, state: State) -> None:
        if state != self.state:
            log.info("state %s -> %s", self.state, state)
        if self.state == State.WEDGED and state != State.WEDGED:
            self.persisted.left_wedged_since_notify = True
        self.state = state
        self._save()

    # -- the schedule ------------------------------------------------------------------------

    def tick(self) -> None:
        """One step of the state machine. The owner thread calls this every interval and on wake."""
        if self.suspended:
            return
        now = self.clock()
        match self.state:
            case State.DISCONNECTED | State.OPEN:
                self._try_open()
            case State.HEALTHY | State.SUSPECT:
                self._health()
            case State.REOPENING:
                if self.next_attempt is None or now >= self.next_attempt:
                    self._reopen()
            case State.WEDGED:
                self._wedged_tick(now)

    def suspend(self) -> None:
        """The Mac is going to sleep: the owner has closed the device. Ticks do nothing until resume().

        Holding the seized HID device across sleep made macOS wait the full 30 s sleep-ack timeout
        (pmset: "python3.12 timed out(30000 ms)"). The Elgato app also closes the device on suspend.
        """
        self.suspended = True
        if not (self.state == State.WEDGED and self.wedged_from_startup):
            self.fails = 0
            self.reopen_cycles = 0
            self._set(State.DISCONNECTED)

    def resume(self) -> None:
        """The Mac woke: the next tick reopens the device."""
        self.suspended = False

    def on_transport_error(self) -> None:
        """Any TransportError or a closed device: start over from DISCONNECTED."""
        if self.state == State.WEDGED and self.wedged_from_startup:
            return
        self.fails = 0
        self.reopen_cycles = 0
        self._set(State.DISCONNECTED)

    # -- transitions -------------------------------------------------------------------------

    def _try_open(self) -> None:
        if not self.device.enumerate_serials():
            self._set(State.DISCONNECTED)
            return
        try:
            self.serial = self.device.open()
            self._set(State.OPEN)
            if self.use_reset:
                self.device.reset()
        except OSError:
            self._set(State.DISCONNECTED)
            return
        self.fails = 0
        self.reopen_cycles = 0
        self._set(State.HEALTHY)

    def healthy(self) -> bool:
        try:
            return self.device.is_open() and self.device.reader_alive() and bool(self.device.firmware_version().strip())
        except OSError:
            return False

    def _health(self) -> None:
        if self.healthy():
            self.fails = 0
            self._set(State.HEALTHY)
            return
        if not self.device.enumerate_serials():
            # Unplugged, not wedged (design: any --not connected()--> DISCONNECTED). Skip the reopen ladder.
            with contextlib.suppress(OSError):
                self.device.close()
            self.on_transport_error()
            return
        self.fails += 1
        if self.fails >= FAILS_TO_REOPEN:
            self.reopen_cycles = 0
            self.next_attempt = None
            self._set(State.REOPENING)
        else:
            self._set(State.SUSPECT)

    def _reopen(self) -> None:
        """One reopen cycle: close, enumerate, open with backoff, optionally reset, check health."""
        with contextlib.suppress(OSError):
            self.device.close()
        if self.device.enumerate_serials():
            try:
                self.serial = self.device.open()
                if self.use_reset:
                    self.device.reset()
                if self.healthy():
                    self.fails = 0
                    self.reopen_cycles = 0
                    self._set(State.HEALTHY)
                    return
            except OSError:
                pass
        self.reopen_cycles += 1
        if self.reopen_cycles >= REOPEN_CYCLES_TO_WEDGE:
            self._enter_wedged()
            return
        backoff = REOPEN_BACKOFF_S[min(self.reopen_cycles - 1, len(REOPEN_BACKOFF_S) - 1)]
        self.next_attempt = self.clock() + timedelta(seconds=backoff)
        self._set(State.REOPENING)

    def _enter_wedged(self) -> None:
        now = self.clock()
        self.next_attempt = now + WEDGED_RETRY
        notified = _parse(self.persisted.notified_at)
        should_notify = notified is None or now - notified >= NOTIFY_EVERY or self.persisted.left_wedged_since_notify
        if self.state != State.WEDGED:
            log.info("state %s -> WEDGED", self.state)
        self.state = State.WEDGED
        if should_notify:
            self.notify_fn(REPLUG_MESSAGE)
            self.persisted.notified_at = _iso(now)
            self.persisted.left_wedged_since_notify = False
        self._save()

    def _wedged_tick(self, now: datetime) -> None:
        if self.next_attempt is not None and now < self.next_attempt:
            return
        self.next_attempt = now + WEDGED_RETRY
        serials = self.device.enumerate_serials()
        replugged = not serials or (self.serial is not None and self.serial not in serials)
        if replugged:
            self.persisted.hang_exits = 0
            self.wedged_from_startup = False
            self.fails = 0
            self.reopen_cycles = 0
            self._set(State.DISCONNECTED)
            return
        if self.wedged_from_startup:
            return  # the device is still the hung one: never open it on a timer
        if self.healthy():
            self.fails = 0
            self.reopen_cycles = 0
            self._set(State.HEALTHY)

    # -- hung calls (called from the watchdog thread) ----------------------------------------

    def check_hang(self, call_started: datetime | None) -> None:
        """call_started is the owner heartbeat: when its current hidapi call began, or None."""
        now = self.clock()
        if call_started is None or now - call_started <= self.health_timeout:
            return
        self.accepting_draws = False
        last_exit = _parse(self.persisted.last_exit)
        if last_exit is None or now - last_exit > HANG_WINDOW:
            self.persisted.hang_exits = 0
        self.persisted.hang_exits += 1
        self.persisted.last_exit = _iso(now)
        self._enter_wedged()
        self.exit_fn(HANG_EXIT)
