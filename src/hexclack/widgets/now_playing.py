"""Now-playing art (Play/Pause key) and the Favourite star (docs/music.md section 5).

Spike s03: one user action can post two playerInfo events within 100 ms, the first with a stale
state, and a skip can post a transient `Stopped`. So the daemon debounces events (MusicWatcher)
and the widgets re-read state through the bridge instead of trusting the notification.
"""

import io
import math
import threading
import time
from collections.abc import Callable
from typing import Protocol

from PIL import Image, ImageDraw, ImageEnhance

from hexclack.music.bridge import NowPlaying
from hexclack.widgets import Event

DEBOUNCE_S = 0.15
# Found on the deck: ScriptingBridge reads the old player state for ~150 ms after a change (osascript
# sees it at once), so a read at the end of the debounce can be stale. A second read settles it.
SETTLE_S = 1.0
# After a press, show what the press did and ignore contrary reads until Music agrees or this passes.
# Measured: a favourite write reads back as the old value for ~10 s; play state lags up to ~250 ms.
HOLD_FAVOURITE_S = 20.0
HOLD_STATE_S = 3.0
SAFETY_POLL_S = 30


def art_tile(data: bytes, size: int = 80) -> Image.Image:
    with Image.open(io.BytesIO(data)) as source:
        return source.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)


def paused(image: Image.Image) -> Image.Image:
    """Art at 40% brightness with a white play triangle."""
    out = ImageEnhance.Brightness(image).enhance(0.4)
    s = out.width
    ImageDraw.Draw(out).polygon([(s * 0.38, s * 0.28), (s * 0.38, s * 0.72), (s * 0.74, s * 0.5)], fill="white")
    return out


def play_tile(size: int = 80) -> Image.Image:
    """Shown when stopped or with no artwork: a white play triangle on black."""
    return paused(Image.new("RGB", (size, size), (60, 60, 60)))


def star_mask(size: int, scale: int = 4) -> Image.Image:
    """A smooth five-point star, drawn large and scaled down (Apple Music's Favourite is a star)."""
    big = size * scale
    cx, cy = big / 2, big * 0.52
    outer, inner = big * 0.40, big * 0.40 * 0.42
    points = []
    for i in range(10):
        r = outer if i % 2 == 0 else inner
        angle = math.radians(-90 + i * 36)
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask.resize((size, size), Image.Resampling.LANCZOS)


FAVOURITE = (250, 45, 72)  # bright red: the track is a favourite
NOT_FAVOURITE = (50, 14, 20)  # the same star in a very dim red (user request: no outline, dim)


def star(filled: bool, size: int = 80) -> Image.Image:
    """Favourite: a solid star, bright red when the track is a favourite, very dim red when not."""
    image = Image.new("RGB", (size, size), "black")
    image.paste(Image.new("RGB", (size, size), FAVOURITE if filled else NOT_FAVOURITE), (0, 0), star_mask(size))
    return image


class Expected:
    """A value a key press just set, shown until a read agrees or the hold time passes.

    Music reports some changes late; without this a stale read after the press shows the old state.
    """

    def __init__(self, hold_s: float, clock: Callable[[], float]) -> None:
        self.hold_s = hold_s
        self.clock = clock
        self.value: object = None
        self.until = 0.0
        self.track: str | None = None

    def set(self, value: object, track: str | None) -> None:
        self.value, self.track, self.until = value, track, self.clock() + self.hold_s

    def resolve(self, read: object, track: str | None) -> object:
        """The value to show: the expected one while held for this track, else the read."""
        if self.until and (self.clock() >= self.until or track != self.track or read == self.value):
            self.until = 0.0  # Music caught up, the hold ran out, or the track changed
        return self.value if self.until else read


class NowPlayingWidget:
    """Draws from the event alone: MusicWatcher fetches the artwork, off the Dispatcher lock."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.subscriptions = {"music"}
        self._art_for: str | None = None
        self._art: Image.Image | None = None
        self._last: tuple[str, str | None] | None = None
        self.expected = Expected(HOLD_STATE_S, clock)

    def render(self, event: Event, size: int = 80) -> Image.Image | None:
        np = event.data["now"]
        assert isinstance(np, NowPlaying)
        if "pressed_state" in event.data:  # this key's press: show the state it moved to, now
            self.expected.set(event.data["pressed_state"], np.track_id)
        state = str(self.expected.resolve(np.state, np.track_id))
        np = NowPlaying(state, np.track_id, np.title, np.artist, np.favorited)
        shown = (np.state, np.track_id)
        if shown == self._last:
            return None  # pause/seek repeats and duplicate events cost nothing
        self._last = shown
        if np.state == "stopped" or np.track_id is None:
            return play_tile(size)
        if np.track_id != self._art_for:  # a new track: use the art the watcher fetched for it
            data = event.data.get("art")
            self._art = art_tile(data, size) if isinstance(data, bytes) else None
            self._art_for = np.track_id
        if self._art is None:
            return play_tile(size)
        return self._art if np.state == "playing" else paused(self._art)


class LoveWidget:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.subscriptions = {"music"}
        self._last: bool | None = None
        self.expected = Expected(HOLD_FAVOURITE_S, clock)

    def render(self, event: Event, size: int = 80) -> Image.Image | None:
        np = event.data["now"]
        assert isinstance(np, NowPlaying)
        if "pressed_favorited" in event.data:  # this key's press: show the new favourite state, now
            self.expected.set(event.data["pressed_favorited"], np.track_id)
        favorited = bool(self.expected.resolve(np.favorited, np.track_id))
        filled = favorited and np.state != "stopped"
        if filled == self._last:
            return None
        self._last = filled
        return star(filled, size)


class Timer(Protocol):
    daemon: bool

    def start(self) -> None: ...
    def cancel(self) -> None: ...


class MusicWatcher:
    """Turns playerInfo notifications (and a slow safety poll) into debounced `music` events."""

    def __init__(
        self,
        read: Callable[[], NowPlaying],
        publish: Callable[[Event], None],
        timer: Callable[[float, Callable[[], None]], Timer] = threading.Timer,
        artwork: Callable[[str], bytes | None] = lambda _track_id: None,
    ) -> None:
        self.read = read
        self.publish = publish
        self.timer = timer
        self.artwork = artwork
        self._pending: list[Timer] = []
        self._lock = threading.Lock()
        self._art_for: str | None = None
        self._art: bytes | None = None
        self._seq = 0  # refreshes run on timer threads; an older read must not publish over a newer one
        self._published = 0
        self._publish_lock = threading.Lock()
        self.latest: dict[str, object] = {}  # the last snapshot published: the screen saver reads it

    def notified(self) -> None:
        """A playerInfo notification or a key press: read state after DEBOUNCE_S of quiet, and once
        more after SETTLE_S, because the first read can still see the old state."""
        with self._lock:
            for pending in self._pending:
                pending.cancel()
            self._pending = [self.timer(DEBOUNCE_S, self.refresh), self.timer(SETTLE_S, self.refresh)]
            for pending in self._pending:
                pending.daemon = True
                pending.start()

    def _snapshot(self) -> dict[str, object]:
        """Read Music (state, track and, for a new track, artwork) on the calling thread: never on the
        Dispatcher lock or the poll thread. Errors read as stopped (bridge never raises)."""
        np = self.read()
        if np.track_id is not None and np.track_id != self._art_for:
            self._art = self.artwork(np.track_id)
            self._art_for = np.track_id
        return {"now": np, "art": self._art if np.track_id == self._art_for else None}

    def refresh(self) -> None:
        with self._publish_lock:
            self._seq += 1
            seq = self._seq
        data = self._snapshot()
        with self._publish_lock:
            if seq < self._published:
                return  # a newer read already published (infodisp: keep snapshots coherent)
            self._published = seq
            self.latest = data
            self.publish(Event("music", data))

    def playing_art(self) -> bytes | None:
        """The current track's artwork while Music is playing (not paused or stopped), else None."""
        np, art = self.latest.get("now"), self.latest.get("art")
        if isinstance(np, NowPlaying) and np.state == "playing" and isinstance(art, bytes):
            return art
        return None

    def refresh_soon(self) -> None:
        """The 30 s safety poll: read on a timer thread so a wedged Music cannot block the caller."""
        pending = self.timer(0, self.refresh)
        pending.daemon = True
        pending.start()

    def pressed(self, changed: dict[str, object]) -> None:
        """A music key press reported what it changed: publish that at once, then re-read as usual."""
        data = self._snapshot()
        if "favorited" in changed:
            data["pressed_favorited"] = changed["favorited"]
        if "state" in changed:
            data["pressed_state"] = changed["state"]
        with self._publish_lock:  # newest: a refresh already in flight must not publish over it
            self._seq += 1
            self._published = self._seq
            self.latest = data
            self.publish(Event("music", data))
        self.notified()
