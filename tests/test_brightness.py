"""Room-light brightness. A bad curve or no hysteresis flickers or blinds; no fallback leaves the
deck stuck dim when sensor is down."""

from hexclack.brightness import HYSTERESIS, AutoBrightness, Curve

CURVE = Curve(((0.0, 15), (30.0, 40), (200.0, 80), (1000.0, 100)))


def test_curve_is_linear_between_points_and_clamped() -> None:
    assert CURVE.at(-5) == 15 and CURVE.at(0) == 15
    assert CURVE.at(15) == 28  # halfway 15 -> 40
    assert CURVE.at(30) == 40 and CURVE.at(115) == 60
    assert CURVE.at(1000) == 100 and CURVE.at(50000) == 100


def test_small_changes_do_not_move_it() -> None:
    auto = AutoBrightness(CURVE, fallback=80)
    assert auto.update(0) == 15  # first reading: dark room (80 -> 15)
    assert auto.update(8) is None  # 15 -> 22: under the hysteresis
    assert auto.update(12) == 25  # 10 points: moves
    assert HYSTERESIS == 8


def test_missing_or_bad_reading_falls_back_to_the_fixed_brightness() -> None:
    auto = AutoBrightness(CURVE, fallback=80)
    auto.update(0)
    assert auto.update(None) == 80  # sensor down or stale: back to normal, not stuck dim
    assert auto.update(None) is None
