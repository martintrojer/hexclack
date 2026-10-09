"""The sensor room key. Wrong here shows an old reading as current, or a dead sensor as fine."""

import json

from hexclack.widgets import Event
from hexclack.widgets import sensors as s

REAL = {  # shape of infodisp's GET /sensors (api.py)
    "status": 0, "aqi": 2, "aqi_str": "Good", "temperature": 21.37, "relative_humidity": 34.4,
    "read_at": "2026-10-05T14:44:16+00:00", "age_s": 40.0,
}  # fmt: skip


def poll(body: object) -> s.Reading:
    data = json.dumps(body).encode() if not isinstance(body, bytes) else body
    reading = s.poll("utils", "2,1", "http://sensor:8044/sensors", fetch=lambda _u: data).data["reading"]
    assert isinstance(reading, s.Reading)
    return reading


def test_parses_infodisps_reply() -> None:
    r = poll(REAL)
    assert (r.temperature, r.humidity, r.aq, r.stale, r.error) == (21.37, 34.4, "Good", False, None)


def test_old_reading_is_stale() -> None:
    assert poll({**REAL, "age_s": 15 * 60 + 1}).stale
    assert not poll({**REAL, "age_s": 15 * 60 - 1}).stale


def test_unreachable_or_bad_reply_is_an_error() -> None:
    def down(_url: str) -> bytes:
        raise OSError("no route to host")

    reading = s.poll("utils", "2,1", "http://sensor:8044/sensors", fetch=down).data["reading"]
    assert isinstance(reading, s.Reading) and reading.error
    assert poll(b"<html>").error
    assert poll({"status": "no data yet"}).error  # infodisp's 503 body before the first read


def test_redraw_only_when_something_shown_changes() -> None:
    w = s.SensorsWidget("utils", "2,1", "sensor")

    def ev(**over: object) -> Event:
        return Event(s.event_name("utils", "2,1"), {"reading": s.parse({**REAL, **over})})

    assert w.render(ev()) is not None
    assert w.render(ev(temperature=21.41, age_s=100)) is None  # same 21.4 shown, still fresh
    assert w.render(ev(temperature=21.46)) is not None  # 21.5
    assert w.render(ev(temperature=21.46, aqi_str="Moderate")) is not None


def test_stale_never_looks_like_an_air_quality_colour() -> None:
    assert s.AMBER not in s.AQ_COLOURS.values()


def test_air_quality_levels_are_clearly_distinct() -> None:
    # User request: a readable traffic light. Every pair of levels differs a lot in hue.
    import colorsys

    def hue(rgb: tuple[int, int, int]) -> float:
        return colorsys.rgb_to_hls(*(c / 255 for c in rgb))[0] * 360

    levels = list(s.AQ_COLOURS.values())
    assert len(levels) == 5
    for i, a in enumerate(levels):
        for b in levels[i + 1 :]:
            d = abs(hue(a) - hue(b))
            assert min(d, 360 - d) >= 15, (a, b)
    # Excellent -> Unhealthy walks from green towards red.
    assert hue(levels[0]) > hue(levels[2]) > hue(levels[3]) > min(hue(levels[4]), 360 - hue(levels[4]))


def test_unhealthy_gets_a_red_border() -> None:
    red = s.AQ_COLOURS["Unhealthy"]
    bad = s.tile("sensor", s.Reading(21.4, 34, "Unhealthy", 40))
    good = s.tile("sensor", s.Reading(21.4, 34, "Good", 40))
    assert bad.getpixel((0, 40)) == red and bad.getpixel((79, 40)) == red
    assert good.getpixel((0, 40)) == (0, 0, 0)


def test_reading_carries_the_light_level() -> None:
    assert poll({**REAL, "visible_light": 27}).light == 27.0
    assert poll(REAL).light is None  # older infodisp without the field
