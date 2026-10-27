"""A toggle whose key shows a device's real state (user report: the blind Dirac toggle drifted).

GET the status URL, read one JSON field, and map it to the toggle state whose `value` matches.
The Runner then sends the action of the *next* state on a press. Unknown or unreachable shows a
red tile and the press is ignored, rather than guessing.
"""

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from hexclack import render
from hexclack.config import Key, Status
from hexclack.widgets import Event

log = logging.getLogger(__name__)

TIMEOUT_S = 3
POLL_S = 30
RED = (255, 69, 58)


def read_status(status: Status, fetch: Callable[[str], bytes] | None = None) -> object:
    """The value of the status field. Raises OSError / ValueError when unreachable or malformed."""
    if fetch is None:
        with urllib.request.urlopen(status.url, timeout=TIMEOUT_S) as reply:
            body = reply.read()
    else:
        body = fetch(status.url)
    data = json.loads(body)
    if not isinstance(data, dict) or status.field not in data:
        raise ValueError(f"{status.url}: no {status.field!r} in the reply")
    return data[status.field]


def state_index(key: Key, value: object) -> int | None:
    for i, state in enumerate(key.toggle):
        if state.value == value:
            return i
    return None


def event_name(screen: str, slot: str) -> str:
    return f"status:{screen}:{slot}"


def poll(screen: str, slot: str, key: Key, fetch: Callable[[str], bytes] | None = None) -> Event:
    assert key.toggle_status is not None
    try:
        value = read_status(key.toggle_status, fetch)
    except Exception as err:  # fail closed on anything (e.g. http.client.IncompleteRead is not an OSError)
        return Event(event_name(screen, slot), {"error": f"{type(err).__name__}: {err}"})
    return Event(event_name(screen, slot), {"value": value})


class StatusToggleWidget:
    """Draws the state the device reports, and tells the Runner which state that is."""

    def __init__(self, screen: str, slot: str, key: Key, base: Path, on_state: Callable[[int | None], None]) -> None:
        self.key = key
        self.base = base
        self.on_state = on_state
        self.subscriptions = {event_name(screen, slot)}
        self._last: object = object()
        self._error_logged = False

    def render(self, event: Event, size: int = 80) -> Image.Image | None:
        error = event.data.get("error")
        index = None if error else state_index(self.key, event.data.get("value"))
        if error and not self._error_logged:
            log.warning("status %s: %s", self.key.toggle_status, error)
            self._error_logged = True
        if not error:
            self._error_logged = False
            if index is None:
                log.warning("status value %r matches no state", event.data.get("value"))
        self.on_state(index)  # the Runner presses relative to this; None blocks presses
        if index == self._last:
            return None
        self._last = index
        if index is None:
            title = self.key.title or "?"
            image = render.placeholder(title, size)
            return Image.blend(image, Image.new("RGB", image.size, RED), 0.55)
        state = self.key.toggle[index]
        return render.key_image(
            Key(slot=self.key.slot, title=state.label, icon=state.icon, tile=self.key.tile),
            self.base,
            size,
        )
