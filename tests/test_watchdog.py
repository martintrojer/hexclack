"""The device state machine (design.md section 4). A wrong transition here wedges the deck silently."""

import json
from pathlib import Path

import pytest

from hexclack.watchdog import HANG_EXIT, State, Watchdog
from tests.fakes import Clock, FakeDevice


class Harness:
    def __init__(self, tmp: Path, device: FakeDevice | None = None, clock: Clock | None = None) -> None:
        self.device = device or FakeDevice()
        self.clock = clock or Clock()
        self.exits: list[int] = []
        self.notes: list[str] = []
        self.state_file = tmp / "state.json"
        self.wd = self.new()

    def new(self) -> Watchdog:
        return Watchdog(self.device, self.clock, self.exits.append, self.notes.append, self.state_file)

    def ticks(self, n: int, seconds: float = 10) -> None:
        for _ in range(n):
            self.wd.tick()
            self.clock.advance(seconds=seconds)

    def saved(self) -> dict:
        return json.loads(self.state_file.read_text())


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def wedge_by_reopen(h: Harness) -> None:
    h.ticks(1)
    h.device.healthy = False
    h.ticks(3)  # SUSPECT, SUSPECT, REOPENING
    h.ticks(3, seconds=20)  # three failed reopen cycles


def test_starts_disconnected(h: Harness) -> None:
    assert h.wd.state == State.DISCONNECTED


def test_disconnected_stays_when_absent(h: Harness) -> None:
    h.device.present = False
    h.ticks(1)
    assert h.wd.state == State.DISCONNECTED and h.device.opened == 0


def test_disconnected_to_healthy_on_open(h: Harness) -> None:
    h.ticks(1)
    assert h.wd.state == State.HEALTHY and h.device.opened == 1 and h.device.resets == 1


def test_open_failure_stays_disconnected(h: Harness) -> None:
    h.device.open_fails = True
    h.ticks(1)
    assert h.wd.state == State.DISCONNECTED


def test_healthy_to_suspect_on_one_failure(h: Harness) -> None:
    h.ticks(1)
    h.device.healthy = False
    h.ticks(1)
    assert h.wd.state == State.SUSPECT


def test_suspect_back_to_healthy(h: Harness) -> None:
    h.ticks(1)
    h.device.healthy = False
    h.ticks(1)
    h.device.healthy = True
    h.ticks(1)
    assert h.wd.state == State.HEALTHY and h.wd.fails == 0


def test_blank_firmware_counts_as_failure(h: Harness) -> None:
    h.ticks(1)
    h.device.firmware = "  "  # the 2026-10-04 symptom: a blank firmware version
    h.ticks(1)
    assert h.wd.state == State.SUSPECT


def test_three_failures_to_reopening(h: Harness) -> None:
    h.ticks(1)
    h.device.healthy = False
    h.ticks(3)
    assert h.wd.state == State.REOPENING


def test_reopening_to_healthy(h: Harness) -> None:
    h.ticks(1)
    h.device.healthy = False
    h.ticks(3)
    h.device.healthy = True
    h.ticks(1)
    assert h.wd.state == State.HEALTHY


def test_reopen_backoff_waits(h: Harness) -> None:
    h.ticks(1)
    h.device.healthy = False
    h.ticks(3)
    h.wd.tick()  # first failed cycle: next attempt in 1 s
    opened = h.device.opened
    h.wd.tick()  # same instant: too early
    assert h.device.opened == opened
    h.clock.advance(seconds=1)
    h.wd.tick()
    assert h.device.opened == opened + 1


def test_three_failed_reopens_to_wedged_and_notifies(h: Harness) -> None:
    wedge_by_reopen(h)
    assert h.wd.state == State.WEDGED
    assert len(h.notes) == 1 and "plug it back in" in h.notes[0]
    assert h.saved()["state"] == "WEDGED"


def test_wedged_from_reopen_retries_every_60s(h: Harness) -> None:
    wedge_by_reopen(h)
    h.device.healthy = True
    h.clock.advance(seconds=30)
    h.wd.tick()
    assert h.wd.state == State.WEDGED
    h.clock.advance(seconds=31)
    h.wd.tick()
    assert h.wd.state == State.HEALTHY


def test_wedged_to_disconnected_on_replug(h: Harness) -> None:
    wedge_by_reopen(h)
    h.device.present = False
    h.clock.advance(seconds=61)
    h.wd.tick()
    assert h.wd.state == State.DISCONNECTED


def test_transport_error_to_disconnected(h: Harness) -> None:
    h.ticks(1)
    h.wd.on_transport_error()
    assert h.wd.state == State.DISCONNECTED


def test_hung_call_persists_and_exits_70(h: Harness) -> None:
    h.ticks(1)
    started = h.clock()
    h.clock.advance(seconds=1)
    h.wd.check_hang(started)
    assert h.exits == []  # within health_timeout_s
    h.clock.advance(seconds=2)
    h.wd.check_hang(started)
    assert h.exits == [HANG_EXIT]
    assert h.saved()["hang_exits"] == 1 and h.saved()["state"] == "WEDGED"
    assert not h.wd.accepting_draws


def test_no_hang_without_call_in_flight(h: Harness) -> None:
    h.clock.advance(seconds=600)
    h.wd.check_hang(None)
    assert h.exits == []


def test_two_hangs_in_10_min_then_restart_does_not_open(h: Harness) -> None:
    for _ in range(2):
        started = h.clock()
        h.clock.advance(seconds=3)
        h.wd.check_hang(started)
        h.clock.advance(seconds=30)  # launchd ThrottleInterval
        h.wd = h.new()
    assert h.saved()["hang_exits"] == 2
    assert h.wd.state == State.WEDGED
    # The hung device stays present. Even if it reports as open and healthy, the watchdog must not touch it:
    # a health read on a hung device is exactly the call that hangs.
    h.device._open = True
    h.device.calls.clear()
    for _ in range(5):
        h.clock.advance(seconds=61)
        h.wd.tick()
    assert h.wd.state == State.WEDGED
    assert set(h.device.calls) == {"enumerate"}, h.device.calls


def test_one_hang_restart_opens_normally(h: Harness) -> None:
    started = h.clock()
    h.clock.advance(seconds=3)
    h.wd.check_hang(started)
    h.wd = h.new()
    assert h.wd.state == State.DISCONNECTED
    h.ticks(1)
    assert h.wd.state == State.HEALTHY


def test_old_hang_resets_counter(h: Harness) -> None:
    started = h.clock()
    h.clock.advance(seconds=3)
    h.wd.check_hang(started)
    h.clock.advance(minutes=11)
    started = h.clock()
    h.clock.advance(seconds=3)
    h.wd.check_hang(started)
    assert h.saved()["hang_exits"] == 1


def test_startup_wedged_leaves_on_serial_change_and_zeroes_counter(h: Harness) -> None:
    for _ in range(2):
        started = h.clock()
        h.clock.advance(seconds=3)
        h.wd.check_hang(started)
    h.wd = h.new()
    assert h.wd.state == State.WEDGED
    h.device.serial = "NEWSERIAL"
    h.clock.advance(seconds=61)
    h.wd.tick()
    assert h.wd.state == State.DISCONNECTED and h.saved()["hang_exits"] == 0
    h.wd.tick()
    assert h.wd.state == State.HEALTHY


def test_notification_rate_limited_across_restarts(h: Harness) -> None:
    for _ in range(3):  # three hangs, each a restart; only one notification
        started = h.clock()
        h.clock.advance(seconds=3)
        h.wd.check_hang(started)
        h.clock.advance(seconds=30)
        h.wd = h.new()
    assert len(h.notes) == 1


def test_notification_again_after_6h(h: Harness) -> None:
    wedge_by_reopen(h)
    h.wd = h.new()
    h.clock.advance(hours=1)
    wedge_by_reopen(h)
    assert len(h.notes) == 1
    h.clock.advance(hours=6)
    h.wd = h.new()
    wedge_by_reopen(h)
    assert len(h.notes) == 2


def test_notification_again_after_leaving_wedged(h: Harness) -> None:
    wedge_by_reopen(h)
    h.device.healthy = True
    h.clock.advance(seconds=61)
    h.wd.tick()
    assert h.wd.state == State.HEALTHY
    h.device.healthy = False
    h.ticks(3)
    h.ticks(3, seconds=20)
    assert h.wd.state == State.WEDGED and len(h.notes) == 2


def test_state_file_is_written_atomically(h: Harness) -> None:
    h.ticks(1)
    assert not h.state_file.with_suffix(".tmp").exists()
    assert h.saved()["state"] == "HEALTHY"


def test_corrupt_state_file_starts_clean(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text("{not json")
    h = Harness(tmp_path)
    assert h.wd.state == State.DISCONNECTED


def test_unplug_goes_straight_to_disconnected(h: Harness) -> None:
    # Found on the real Mini: a clean unplug took the SUSPECT, SUSPECT, REOPENING path (30 s).
    h.ticks(1)
    h.device.present = False
    h.device.healthy = False
    h.ticks(1)
    assert h.wd.state == State.DISCONNECTED and h.wd.fails == 0
    h.device.present = True
    h.device.healthy = True
    h.ticks(1)
    assert h.wd.state == State.HEALTHY


def test_suspend_disconnects_and_ticks_do_nothing_until_resume(h: Harness) -> None:
    # Holding the device across sleep delayed macOS sleep by 30 s; the owner closes it and suspends.
    h.ticks(1)
    h.wd.suspend()
    assert h.wd.state == State.DISCONNECTED
    h.device.calls.clear()
    h.ticks(5)
    assert h.device.calls == []  # nothing touches the device while the Mac sleeps
    h.wd.resume()
    h.ticks(1)
    assert h.wd.state == State.HEALTHY


def test_suspend_keeps_startup_wedge(h: Harness) -> None:
    for _ in range(2):
        started = h.clock()
        h.clock.advance(seconds=3)
        h.wd.check_hang(started)
    h.wd = h.new()
    h.wd.suspend()
    h.wd.resume()
    assert h.wd.state == State.WEDGED and h.wd.wedged_from_startup
