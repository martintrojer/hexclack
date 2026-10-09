"""Room temperature and air quality from infodisp on sensor (GET http://sensor:8044/sensors).

infodisp serves its cached sample with `read_at`/`age_s` (infodisp api.py). The key shows the
temperature large, the air quality word below it in its colour, and humidity small. Polling it also
says sensor and infodisp are alive: unreachable shows a red error, an old sample shows amber.
"""

import json
import logging
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image, ImageDraw

from hexclack import tiles
from hexclack.widgets import Event

log = logging.getLogger(__name__)

TIMEOUT_S = 3
POLL_S = 60
STALE_S = 15 * 60  # infodisp reads every 5 min: three missed readings
GREY, DIM = (166, 173, 200), (108, 112, 134)  # Mocha subtext0 / overlay0
RED = (243, 139, 168)  # Mocha red: errors
# Air quality as a traffic light (user request). Mocha's pastels sit too close together for this
# (maroon vs red, yellow vs white), so these are saturated, one distinct hue per level.
AQ_COLOURS = {  # infodisp's aqi_str (ENS160 UBA index 1-5); "Unknown" while the sensor warms up
    "Excellent": (64, 200, 90),  # green
    "Good": (40, 190, 170),  # teal-green
    "Moderate": (240, 200, 0),  # yellow
    "Poor": (255, 130, 20),  # orange
    "Unhealthy": (235, 40, 50),  # red
}
AMBER = DIM  # stale: a grey that is on no point of the scale


@dataclass(frozen=True)
class Reading:
    temperature: float | None
    humidity: float | None
    aq: str
    age_s: float | None
    error: str | None = None
    light: float | None = None  # LTR303 visible_light (raw count): drives auto brightness

    @property
    def stale(self) -> bool:
        return self.age_s is None or self.age_s > STALE_S


def parse(doc: object) -> Reading:
    """infodisp's /sensors JSON. Raises ValueError when it is not in the expected shape."""
    if not isinstance(doc, dict) or not isinstance(doc.get("temperature"), int | float):
        raise ValueError("no temperature in the reply")
    hum, age, light = doc.get("relative_humidity"), doc.get("age_s"), doc.get("visible_light")
    return Reading(
        light=float(light) if isinstance(light, int | float) else None,
        temperature=float(doc["temperature"]),
        humidity=float(hum) if isinstance(hum, int | float) else None,
        aq=str(doc.get("aqi_str") or "Unknown"),
        age_s=float(age) if isinstance(age, int | float) else None,
    )


def tile(title: str, r: Reading, size: int = 80) -> Image.Image:
    image = Image.new("RGB", (size, size), "black")
    draw = ImageDraw.Draw(image)
    draw.text((size // 2, size * 0.13), title, font=tiles.bold(max(9, size // 8)), fill=GREY, anchor="mm")
    if r.error:
        draw.text((size // 2, size * 0.5), "error", font=tiles.bold(size // 4), fill=RED, anchor="mm")
        small = tiles.bold(max(7, size // 11))
        draw.text((size // 2, size * 0.8), r.error, font=small, fill=GREY, anchor="mm")
        return image
    temp = f"{r.temperature:.1f}°" if r.temperature is not None else "-"
    font, _ = tiles.fit_text(draw, temp, size - 6, size // 3, size // 6, step=1)
    draw.text((size // 2, size * 0.43), temp, font=font, fill="white" if not r.stale else AMBER, anchor="mm")
    line = f"stale {int((r.age_s or 0) // 60)}m" if r.stale else r.aq
    colour = AMBER if r.stale else AQ_COLOURS.get(r.aq, GREY)
    if not r.stale and r.aq == "Unhealthy":  # stand out across the room: a red border
        width = max(2, size // 20)
        draw.rectangle((0, 0, size - 1, size - 1), outline=AQ_COLOURS["Unhealthy"], width=width)
    aq_font, _ = tiles.fit_text(draw, line, size - 6, max(9, size // 7), max(7, size // 11), step=1)
    draw.text((size // 2, size * 0.68), line, font=aq_font, fill=colour, anchor="mm")
    if r.humidity is not None:
        hum_font = tiles.bold(max(7, size // 10))
        draw.text((size // 2, size * 0.88), f"{r.humidity:.0f}% RH", font=hum_font, fill=GREY, anchor="mm")
    return image


def event_name(screen: str, slot: str) -> str:
    return f"sensors:{screen}:{slot}"


def poll(screen: str, slot: str, url: str, fetch: Callable[[str], bytes] | None = None) -> Event:
    """One GET; any failure (sensor or infodisp down, bad reply) becomes an error reading."""
    try:
        if fetch is None:
            with urllib.request.urlopen(url, timeout=TIMEOUT_S) as reply:
                body = reply.read()
        else:
            body = fetch(url)
        reading = parse(json.loads(body))
    except Exception as err:
        reading = Reading(None, None, "Unknown", None, error=type(err).__name__)
        log.debug("sensors %s: %s", url, err)
    return Event(event_name(screen, slot), {"reading": reading})


class SensorsWidget:
    def __init__(self, screen: str, slot: str, title: str) -> None:
        self.title = title
        self.subscriptions = {event_name(screen, slot)}
        self._last: tuple[object, ...] | None = None
        self.latest: Reading | None = None

    def render(self, event: Event, size: int = 80) -> Image.Image | None:
        r = event.data["reading"]
        assert isinstance(r, Reading)
        self.latest = r  # read by the screen saver's alerts
        shown = (
            None if r.temperature is None else round(r.temperature, 1),
            None if r.humidity is None else round(r.humidity),
            r.aq,
            r.stale,
            r.error,
            int((r.age_s or 0) // 60) if r.stale else None,
        )
        if shown == self._last:
            return None
        self._last = shown
        return tile(self.title, r, size)
