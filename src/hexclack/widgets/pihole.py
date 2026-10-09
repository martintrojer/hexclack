"""Pi-hole status on its key: blocking on, off, or the countdown until it turns back on."""

import logging

from PIL import Image, ImageDraw

from hexclack import tiles
from hexclack.pihole import PiholeClient
from hexclack.widgets import Event

log = logging.getLogger(__name__)

POLL_S = 30
GREEN, AMBER, RED = (48, 209, 88), (255, 159, 10), (255, 69, 58)


def status_tile(
    title: str, line: str, colour: tuple[int, int, int], blocked: int | None = None, size: int = 80
) -> Image.Image:
    """Title on top, the blocked-in-24 h count large in the middle, the state line in its colour below."""
    image = Image.new("RGB", (size, size), "black")
    draw = ImageDraw.Draw(image)
    draw.text((size // 2, size * 0.17), title, font=tiles.bold(max(9, size // 7)), fill="white", anchor="mm")
    count = compact(blocked) if blocked is not None else "-"
    font, _ = tiles.fit_text(draw, count, size - 8, max(12, size // 3), max(10, size // 6), step=1)
    draw.text((size // 2, size * 0.5), count, font=font, fill="white", anchor="mm")
    r = max(3, size // 16)
    y = size * 0.83
    text = tiles.bold(max(8, size // 8))
    width = draw.textlength(line, font=text)
    x = size / 2 - (width + 2 * r + 4) / 2
    draw.ellipse((x, y - r, x + 2 * r, y + r), fill=colour)
    draw.text((x + 2 * r + 4, y), line, font=text, fill=colour, anchor="lm")
    return image


def compact(n: int) -> str:
    """14733 -> 14.7k, 1236 -> 1236, 2_400_000 -> 2.4M: fits a 80 px key."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1000:.1f}k"
    return str(n)


def countdown(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}" if m < 60 else f"{m // 60}h{m % 60:02d}"


class PiholeWidget:
    def __init__(self, host: str, title: str) -> None:
        self.host = host
        self.title = title
        self.subscriptions = {f"pihole:{host}"}
        self._last: tuple[str, int | None, int | None] | None = None
        self._error_logged = False

    def render(self, event: Event, size: int = 80) -> Image.Image | None:
        error = event.data.get("error")
        if error:
            shown: tuple[str, int | None, int | None] = ("error", None, None)
            if not self._error_logged:  # a missing Keychain entry logs once, not every poll
                log.warning("pihole %s: %s", self.host, error)
                self._error_logged = True
        else:
            self._error_logged = False
            timer = event.data.get("timer")
            blocked = event.data.get("blocked")
            shown = (
                str(event.data.get("blocking")),
                int(timer) if isinstance(timer, int | float) else None,
                blocked if isinstance(blocked, int) else None,
            )
        if shown == self._last:
            return None
        self._last = shown
        state, timer, blocked = shown
        if state == "error":
            return status_tile(self.title, "error", RED, None, size)
        if state == "enabled":
            return status_tile(self.title, "pihole on", GREEN, blocked, size)
        if state == "disabled":  # "pihole off 59:41" is too wide for the key, so the countdown drops "pihole"
            return status_tile(self.title, f"off {countdown(timer)}" if timer else "pihole off", AMBER, blocked, size)
        return status_tile(self.title, state, RED, blocked, size)


def poll(client: PiholeClient) -> Event:
    """One status read as an event. Errors become an event too, so the key shows them."""
    try:
        body = client.status()
        blocked = client.blocked_24h()
    except Exception as err:  # PiholeError, or anything unexpected from the HTTP layer: show an error tile
        return Event(f"pihole:{client.host}", {"error": f"{type(err).__name__}: {err}"})
    return Event(
        f"pihole:{client.host}", {"blocking": body.get("blocking"), "timer": body.get("timer"), "blocked": blocked}
    )
