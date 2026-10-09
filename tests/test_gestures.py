"""Gesture timing. A wrong window fires the wrong action (skip instead of previous) with no error."""

from hexclack.gestures import Gestures

TAP = {"tap"}
TAP_DOUBLE_HOLD = {"tap", "double", "hold"}  # the Skip key
TAP_HOLD = {"tap", "hold"}  # the Bot keys


def press(g: Gestures, t: float, up_after: float, has: set[str], key: int = 0) -> list[str]:
    return g.event(key, True, t, has) + g.event(key, False, t + up_after, has)


def test_tap_only_fires_on_release_at_once() -> None:
    g = Gestures()
    assert g.event(0, True, 0.0, TAP) == []
    assert g.event(0, False, 0.05, TAP) == ["tap"]


def test_tap_with_double_waits_for_the_window() -> None:
    g = Gestures(double_ms=300)
    assert press(g, 0.0, 0.05, TAP_DOUBLE_HOLD) == []
    assert g.poll(0.30, {0: TAP_DOUBLE_HOLD}) == []  # 0.25 s after release: still waiting
    assert g.poll(0.36, {0: TAP_DOUBLE_HOLD}) == [(0, "tap")]
    assert g.poll(0.50, {0: TAP_DOUBLE_HOLD}) == []  # fires once


def test_double_inside_window_gives_double_and_no_tap() -> None:
    g = Gestures(double_ms=300)
    assert press(g, 0.0, 0.05, TAP_DOUBLE_HOLD) == []
    assert press(g, 0.20, 0.05, TAP_DOUBLE_HOLD) == ["double"]
    assert g.poll(1.0, {0: TAP_DOUBLE_HOLD}) == []


def test_second_press_after_window_is_two_taps() -> None:
    g = Gestures(double_ms=300)
    press(g, 0.0, 0.05, TAP_DOUBLE_HOLD)
    assert g.poll(0.40, {0: TAP_DOUBLE_HOLD}) == [(0, "tap")]
    press(g, 0.50, 0.05, TAP_DOUBLE_HOLD)
    assert g.poll(0.90, {0: TAP_DOUBLE_HOLD}) == [(0, "tap")]


def test_hold_fires_while_down_and_suppresses_tap() -> None:
    g = Gestures(hold_ms=500)
    g.event(0, True, 0.0, TAP_HOLD)
    assert g.poll(0.49, {0: TAP_HOLD}) == []
    assert g.poll(0.50, {0: TAP_HOLD}) == [(0, "hold")]
    assert g.poll(0.70, {0: TAP_HOLD}) == []  # once
    assert g.event(0, False, 0.80, TAP_HOLD) == []  # release after hold: nothing


def test_release_under_hold_ms_is_a_tap() -> None:
    g = Gestures(hold_ms=500)
    g.event(0, True, 0.0, TAP_HOLD)
    assert g.poll(0.3, {0: TAP_HOLD}) == []
    assert g.event(0, False, 0.45, TAP_HOLD) == ["tap"]


def test_release_at_threshold_before_poll_is_a_hold() -> None:
    g = Gestures(hold_ms=500)
    g.event(0, True, 0.0, TAP_HOLD)
    assert g.event(0, False, 0.55, TAP_HOLD) == ["hold"]


def test_no_hold_defined_long_press_is_a_tap() -> None:
    g = Gestures(hold_ms=500)
    assert press(g, 0.0, 2.0, TAP) == ["tap"]


def test_keys_are_independent() -> None:
    g = Gestures(double_ms=300)
    press(g, 0.0, 0.05, TAP_DOUBLE_HOLD, key=5)
    assert press(g, 0.1, 0.05, TAP, key=1) == ["tap"]
    assert g.poll(0.4, {5: TAP_DOUBLE_HOLD, 1: TAP}) == [(5, "tap")]


def test_up_without_down_is_ignored() -> None:
    assert Gestures().event(0, False, 1.0, TAP) == []
