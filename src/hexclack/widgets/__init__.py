"""Live keys (docs/design.md section 7). A widget owns one key and returns its image on an event.

The `Dispatcher` sends each event to the widgets that subscribe to it and enqueues a draw only
when the widget's image changed. Rendering never runs on a timer; timers only produce events.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    name: str  # e.g. "music", "pihole:server:8000"
    data: dict[str, object] = field(default_factory=dict)


class Widget(Protocol):
    subscriptions: set[str]

    def render(self, event: Event, size: int = 80) -> Image.Image | None:
        """The new key image, or None if nothing changed."""
        ...


@dataclass
class Placement:
    screen: str
    index: int
    widget: Widget


class Dispatcher:
    def __init__(self, draw: Callable[[str, int, Image.Image], None]) -> None:
        self.draw = draw  # (screen, key index, image): the deck decides whether that screen is visible
        self.placements: list[Placement] = []
        self.latest: dict[tuple[str, int], Image.Image] = {}
        self._lock = threading.Lock()

    def add(self, screen: str, index: int, widget: Widget) -> None:
        self.placements.append(Placement(screen, index, widget))

    def image(self, screen: str, index: int) -> Image.Image | None:
        return self.latest.get((screen, index))

    def publish(self, event: Event) -> None:
        with self._lock:
            for p in self.placements:
                if event.name not in p.widget.subscriptions:
                    continue
                try:
                    image = p.widget.render(event)
                except Exception:
                    log.exception("widget on %s key %d failed", p.screen, p.index)
                    continue
                if image is not None:
                    self.latest[(p.screen, p.index)] = image
                    self.draw(p.screen, p.index, image)
