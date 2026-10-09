"""A host's health summary on one key, read (GET only) from a health.json such as http://server/health.json.

Format (as served by server): {"checked_at": ISO-8601, "data": {"status"}, "services": {id: {"label",
"section", "status"}}}, status one of healthy / unhealthy / not-installed. Like server's own page,
results older than STALE_S are treated as unknown. Display only: the key has no action.
"""

import json
import logging
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from PIL import Image, ImageDraw

from hexclack import tiles
from hexclack.widgets import Event

log = logging.getLogger(__name__)

TIMEOUT_S = 3
POLL_S = 60  # server's page polls every 60 s
STALE_S = 180  # server's page: older than 3 minutes is stale
GREEN, AMBER, RED, GREY = (166, 227, 161), (249, 226, 175), (243, 139, 168), (166, 173, 200)  # Mocha


@dataclass(frozen=True)
class Summary:
    healthy: int
    total: int  # not-installed services are not counted
    unhealthy: tuple[str, ...]  # labels
    age_s: float | None  # seconds since checked_at
    error: str | None = None

    @property
    def stale(self) -> bool:
        return self.age_s is None or self.age_s > STALE_S


def summarize(doc: object, now: datetime) -> Summary:
    """Parse a health.json document. Raises ValueError when it is not in the expected shape."""
    if not isinstance(doc, dict) or not isinstance(doc.get("services"), dict):
        raise ValueError("no services in the reply")
    entries: dict[str, dict[str, object]] = {k: v for k, v in doc["services"].items() if isinstance(v, dict)}
    if isinstance(doc.get("data"), dict):
        entries = {"data": {"label": "/data", **doc["data"]}, **entries}
    counted = {k: v for k, v in entries.items() if v.get("status") != "not-installed"}
    unhealthy = tuple(str(v.get("label") or k) for k, v in counted.items() if v.get("status") != "healthy")
    age = None
    try:
        checked = datetime.fromisoformat(str(doc.get("checked_at")).replace("Z", "+00:00"))
        age = (now - checked).total_seconds()
    except ValueError:
        pass
    return Summary(len(counted) - len(unhealthy), len(counted), unhealthy, age)


def age_text(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h"


def tile(title: str, summary: Summary, size: int = 80) -> Image.Image:
    """Title, a coloured N/M count, and the first unhealthy label or the result's age."""
    image = Image.new("RGB", (size, size), "black")
    draw = ImageDraw.Draw(image)
    draw.text((size // 2, size * 0.16), title, font=tiles.bold(max(9, size // 7)), fill="white", anchor="mm")
    if summary.error:
        colour, big, small = RED, "error", summary.error
    elif summary.stale:
        colour, big, small = AMBER, f"{summary.healthy}/{summary.total}", f"stale {age_text(summary.age_s)}"
    elif summary.unhealthy:
        colour, big, small = RED, f"{summary.healthy}/{summary.total}", summary.unhealthy[0]
    else:
        colour, big, small = GREEN, f"{summary.healthy}/{summary.total}", f"checked {age_text(summary.age_s)}"
    font, _ = tiles.fit_text(draw, big, size - 8, max(12, size // 3), max(10, size // 6), step=1)
    draw.text((size // 2, size * 0.5), big, font=font, fill=colour, anchor="mm")
    small_font, lines = tiles.fit_text(draw, small, size - 6, max(8, size // 8), max(7, size // 11), step=1)
    draw.text((size // 2, size * 0.82), lines[0] if lines else small, font=small_font, fill=GREY, anchor="mm")
    return image


def event_name(screen: str, slot: str) -> str:
    return f"health:{screen}:{slot}"


def poll(screen: str, slot: str, url: str, fetch: Callable[[str], bytes] | None = None) -> Event:
    """One GET of the health.json, as an event. Any failure becomes an error event (fail closed)."""
    try:
        if fetch is None:
            with urllib.request.urlopen(url, timeout=TIMEOUT_S) as reply:
                body = reply.read()
        else:
            body = fetch(url)
        summary = summarize(json.loads(body), datetime.now(UTC))
    except Exception as err:
        summary = Summary(0, 0, (), None, error=type(err).__name__)
        log.debug("health %s: %s", url, err)
    return Event(event_name(screen, slot), {"summary": summary})


class HealthWidget:
    def __init__(self, screen: str, slot: str, title: str) -> None:
        self.title = title
        self.subscriptions = {event_name(screen, slot)}
        self._last: tuple[object, ...] | None = None
        self.latest: Summary | None = None

    def render(self, event: Event, size: int = 80) -> Image.Image | None:
        summary = event.data["summary"]
        assert isinstance(summary, Summary)
        self.latest = summary  # read by the screen saver's alerts
        age_bucket = age_text(summary.age_s)  # redraw when the shown age changes, not every poll
        shown = (summary.healthy, summary.total, summary.unhealthy, summary.stale, summary.error, age_bucket)
        if shown == self._last:
            return None
        self._last = shown
        return tile(self.title, summary, size)
