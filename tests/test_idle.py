"""Idle states. A saver that never starts, never turns off, or a wake press that fires an action
(e.g. sends a Message) all go unnoticed until they bite."""

from datetime import UTC, datetime, timedelta

from hexclack.idle import Idle, IdleTimer

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_clock_at_30_then_off_at_120() -> None:
    t = IdleTimer(30, 120, T0)
    assert t.tick(at(29)) is None and t.state == Idle.AWAKE
    assert t.tick(at(30)) == Idle.CLOCK
    assert t.tick(at(31)) is None  # reported once
    assert t.tick(at(120)) == Idle.OFF
    assert t.tick(at(500)) is None and t.state == Idle.OFF


def test_any_key_wakes_and_the_wake_press_is_swallowed() -> None:
    for wake_at, state in ((45, Idle.CLOCK), (200, Idle.OFF)):
        t = IdleTimer(30, 120, T0)
        t.tick(at(wake_at))
        assert t.state == state
        assert t.key(3, True, at(wake_at)) is False  # down: wake, no-op
        assert t.state == Idle.AWAKE
        assert t.key(3, False, at(wake_at)) is False  # its up: also swallowed (no tap)
        assert t.key(3, True, at(wake_at + 0.1)) is True  # the next press is real
        assert t.key(3, False, at(wake_at + 0.1)) is True


def test_presses_while_awake_pass_through() -> None:
    t = IdleTimer(30, 120, T0)
    assert t.key(0, True, at(1)) is True
    assert t.key(0, False, at(1)) is True


def test_press_restarts_the_countdown() -> None:
    t = IdleTimer(30, 120, T0)
    t.key(0, True, at(25))
    t.key(0, False, at(25))
    assert t.tick(at(50)) is None
    assert t.tick(at(55)) == Idle.CLOCK


def test_zero_disables_a_stage() -> None:
    no_clock = IdleTimer(0, 120, T0)
    assert no_clock.tick(at(60)) is None
    assert no_clock.tick(at(120)) == Idle.OFF
    no_off = IdleTimer(30, 0, T0)
    assert no_off.tick(at(30)) == Idle.CLOCK
    assert no_off.tick(at(10_000)) is None and no_off.state == Idle.CLOCK
    never = IdleTimer(0, 0, T0)
    assert never.tick(at(10_000)) is None


def test_long_gap_goes_straight_to_off() -> None:
    # A tick that first fires after 2 h (e.g. the Mac was busy) must not show the clock first.
    t = IdleTimer(30, 120, T0)
    assert t.tick(at(130)) == Idle.OFF


def test_off_turns_the_backlight_off_and_waking_restores_it() -> None:
    # User report: "off" looked black with the backlight still lit.
    from hexclack.idle import brightness_for

    assert brightness_for(Idle.OFF, 80) == 0
    assert brightness_for(Idle.AWAKE, 80) == 80
    assert brightness_for(Idle.CLOCK, 80) == 80  # the clock is meant to be seen


def test_an_alert_holds_the_clock_past_sleep() -> None:
    # User request: past sleep time, a warning keeps the clock and its banner up instead of black;
    # off once it clears, back to the clock if one appears again.
    t = IdleTimer(30, 120, T0)
    assert t.tick(at(20), alerting=True) is None and t.state == Idle.AWAKE  # under 30 m: normal
    assert t.tick(at(30), alerting=True) == Idle.CLOCK
    assert t.tick(at(130), alerting=True) is None and t.state == Idle.CLOCK
    assert t.tick(at(131), alerting=False) == Idle.OFF
    assert t.tick(at(140), alerting=True) == Idle.CLOCK
    assert t.tick(at(150), alerting=False) == Idle.OFF


def test_an_alert_after_a_long_gap_shows_the_clock_not_off() -> None:
    t = IdleTimer(30, 120, T0)
    assert t.tick(at(130), alerting=True) == Idle.CLOCK


def test_quiet_hours_are_22_to_06_local() -> None:
    # User request: at night an alert must not bring back the clock and banner once asleep.
    from hexclack.idle import quiet_hours

    def h(hour: int, minute: int = 0) -> bool:
        return quiet_hours(datetime(2026, 10, 5, hour, minute))

    assert not h(21, 59)
    assert h(22) and h(23, 59) and h(0) and h(5, 59)
    assert not h(6) and not h(12)
