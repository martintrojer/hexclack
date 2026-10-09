"""Live keys. The failures here are silent: stale art after a skip, a Favourite star that never updates, or
an artwork fetch on every event (spike s03: duplicate events are normal) that slows every press."""

import io
import logging
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from hexclack import config, render
from hexclack.config import Key
from hexclack.music.bridge import NowPlaying
from hexclack.pihole import PiholeClient, PiholeError
from hexclack.widgets import Dispatcher, Event, status
from hexclack.widgets import pihole as pw
from hexclack.widgets.now_playing import DEBOUNCE_S, SETTLE_S, LoveWidget, MusicWatcher, NowPlayingWidget


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (120, 120), (10, 200, 30)).save(buf, "JPEG")
    return buf.getvalue()


JPEG = _jpeg()


def music(state: str, track: str | None = "T1", fav: bool = False, art: bytes | None = JPEG) -> Event:
    return Event("music", {"now": NowPlaying(state, track, "title", "artist", fav), "art": art})


class ArtCounter:
    def __init__(self, data: bytes | None = JPEG) -> None:
        self.calls = 0
        self.data = data

    def __call__(self, _track_id: str | None = None) -> bytes | None:
        self.calls += 1
        return self.data


def test_artwork_fetched_once_per_track_not_per_event() -> None:
    # The watcher fetches artwork (off the Dispatcher lock): once per track, not per event.
    art = ArtCounter()
    tracks = iter(["T1", "T1", "T1", "T2"])
    events: list[Event] = []
    watcher = MusicWatcher(lambda: NowPlaying("playing", next(tracks)), events.append, artwork=art)
    for _ in range(3):
        watcher.refresh()
    assert art.calls == 1 and all(e.data["art"] == JPEG for e in events)
    watcher.refresh()  # skip: new art
    assert art.calls == 2


def test_widget_redraws_only_on_change() -> None:
    w = NowPlayingWidget()
    assert w.render(music("playing")) is not None
    assert w.render(music("playing")) is None  # duplicate event: no redraw
    assert w.render(music("paused")) is not None  # pause redraws from the cached art
    assert w.render(music("playing")) is not None


def test_paused_is_dimmed_art_and_stopped_is_play_tile() -> None:
    w = NowPlayingWidget()
    playing = w.render(music("playing"))
    paused = w.render(music("paused"))
    stopped = w.render(music("stopped", track=None))
    assert playing is not None and paused is not None and stopped is not None
    assert playing.getpixel((5, 5)) != paused.getpixel((5, 5))  # dimmed
    assert stopped.getpixel((5, 5)) != playing.getpixel((5, 5))


def test_track_without_artwork_shows_play_tile() -> None:
    w = NowPlayingWidget()
    image = w.render(music("playing", art=None))
    assert image is not None and image.size == (80, 80)


def test_favourite_star_follows_favorited_and_skips_repeats() -> None:
    w = LoveWidget()
    empty = w.render(music("playing", fav=False))
    assert empty is not None
    assert w.render(music("playing", fav=False)) is None
    full = w.render(music("playing", fav=True))
    assert full is not None and full.tobytes() != empty.tobytes()


class FakeTimer:
    """Collects scheduled callbacks; the test fires them."""

    def __init__(self) -> None:
        self.pending: list[tuple[float, Callable[[], None], bool]] = []

    def __call__(self, delay: float, fn: Callable[[], None]) -> "FakeTimer.Handle":
        handle = FakeTimer.Handle(self, delay, fn)
        return handle

    class Handle:
        def __init__(self, owner: "FakeTimer", delay: float, fn: Callable[[], None]) -> None:
            self.owner, self.delay, self.fn, self.daemon = owner, delay, fn, False
            self.cancelled = False

        def start(self) -> None:
            self.owner.pending.append((self.delay, self.fire, self.cancelled))

        def cancel(self) -> None:
            self.cancelled = True

        def fire(self) -> None:
            if not self.cancelled:
                self.fn()


def test_watcher_debounces_a_burst_into_one_read() -> None:
    reads: list[int] = []

    def read() -> NowPlaying:
        reads.append(1)
        return NowPlaying("playing")

    timer = FakeTimer()
    watcher = MusicWatcher(read, lambda _e: None, timer=timer)
    for _ in range(3):  # s03: one action posts two or three events within 100 ms
        watcher.notified()
    for _, fire, _ in timer.pending:
        fire()
    # One read after the debounce and one settle read: two, not one per event.
    assert len(reads) == 2
    assert sorted({delay for delay, _, _ in timer.pending}) == [DEBOUNCE_S, SETTLE_S]


def test_settle_read_corrects_a_stale_first_read() -> None:
    # Found on the deck: the bridge reads "playing" for ~150 ms after a pause, so the first read is stale.
    states = iter(["playing", "paused"])
    drawn: list[str] = []
    bright = NowPlayingWidget().render(music("playing"))
    assert bright is not None

    def classify(_s: str, _i: int, img: Image.Image) -> None:
        drawn.append("art" if img.tobytes() == bright.tobytes() else "dim")

    d = Dispatcher(classify)
    d.add("home", 4, NowPlayingWidget())
    d.publish(music("playing"))
    timer = FakeTimer()
    watcher = MusicWatcher(lambda: NowPlaying(next(states), "T1"), d.publish, timer=timer)
    watcher.notified()
    for _, fire, _ in timer.pending:
        fire()
    assert drawn == ["art", "dim"]


def test_dispatcher_routes_by_subscription_and_keeps_latest() -> None:
    drawn: list[tuple[str, int]] = []
    d = Dispatcher(lambda s, i, _img: drawn.append((s, i)))
    d.add("home", 4, NowPlayingWidget())
    d.add("utils", 1, pw.PiholeWidget("server:8000", "server"))
    d.publish(music("playing"))
    assert drawn == [("home", 4)] and d.image("home", 4) is not None and d.image("utils", 1) is None


def test_failing_widget_does_not_stop_the_others() -> None:
    class Broken:
        def __init__(self) -> None:
            self.subscriptions = {"music"}

        def render(self, event: Event, size: int = 80) -> Image.Image | None:
            raise RuntimeError("boom")

    drawn: list[int] = []
    d = Dispatcher(lambda _s, i, _img: drawn.append(i))
    d.add("home", 0, Broken())
    d.add("home", 4, NowPlayingWidget())
    d.publish(music("playing"))
    assert drawn == [4]


def test_pihole_states_and_countdown() -> None:
    w = pw.PiholeWidget("server:8000", "server")
    ev = "pihole:server:8000"
    on = w.render(Event(ev, {"blocking": "enabled", "timer": None}))
    off = w.render(Event(ev, {"blocking": "disabled", "timer": 3599.4}))
    assert on is not None and off is not None and on.tobytes() != off.tobytes()
    assert w.render(Event(ev, {"blocking": "disabled", "timer": 3599.1})) is None  # same second: no redraw
    assert pw.countdown(3599) == "59:59" and pw.countdown(5400) == "1h30"


def test_pihole_error_logs_once(caplog: pytest.LogCaptureFixture) -> None:
    # A missing Keychain entry must log once, not every 30 s poll.
    w = pw.PiholeWidget("server:8000", "server")
    ev = Event("pihole:server:8000", {"error": "no Keychain password"})
    with caplog.at_level(logging.WARNING, logger="hexclack.widgets.pihole"):
        assert w.render(ev) is not None
        for _ in range(5):
            w.render(ev)
    assert len(caplog.records) == 1


def test_pihole_poll_turns_errors_into_events() -> None:
    class Failing(PiholeClient):
        def status(self) -> dict[str, object]:
            raise PiholeError("no Keychain password for server:8000")

    event = pw.poll(Failing("server:8000", password=lambda: ""))
    assert event.name == "pihole:server:8000" and "Keychain" in str(event.data["error"])


def test_pihole_redraws_when_the_blocked_count_changes() -> None:
    # The Elgato plugin showed ads_blocked_today; a count stuck at its first value would go unnoticed.
    w = pw.PiholeWidget("server:8000", "server")
    ev = "pihole:server:8000"
    assert w.render(Event(ev, {"blocking": "enabled", "timer": None, "blocked": 14733})) is not None
    assert w.render(Event(ev, {"blocking": "enabled", "timer": None, "blocked": 14733})) is None
    assert w.render(Event(ev, {"blocking": "enabled", "timer": None, "blocked": 14740})) is not None
    assert pw.compact(14733) == "14.7k" and pw.compact(1236) == "1236" and pw.compact(2_400_000) == "2.4M"


# -- status-backed toggle widget ---------------------------------------------------------------------


ROOT = Path(__file__).parent.parent
DIRAC_KEY = config.load(ROOT / "tests/data/layout.toml").screens["utils"].keys["0,1"]
BASE = ROOT / "tests/data"


def test_status_widget_shows_the_state_the_device_reports() -> None:
    key, base = DIRAC_KEY, BASE
    seen: list[int | None] = []
    w = status.StatusToggleWidget("utils", "1,1", key, base, seen.append)
    ev = status.event_name("utils", "1,1")
    off = w.render(Event(ev, {"value": 0}))
    on = w.render(Event(ev, {"value": 1}))
    assert seen == [0, 1]
    assert off is not None and on is not None
    expected_on = render.key_image(Key(slot="1,1", title="Dirac On", icon=key.toggle[1].icon), base)
    assert on.tobytes() == expected_on.tobytes()
    assert w.render(Event(ev, {"value": 1})) is None  # unchanged: no redraw


def test_status_widget_unreachable_or_unknown_blocks_presses() -> None:
    key, base = DIRAC_KEY, BASE
    seen: list[int | None] = []
    w = status.StatusToggleWidget("utils", "1,1", key, base, seen.append)
    ev = status.event_name("utils", "1,1")
    assert w.render(Event(ev, {"error": "timed out"})) is not None
    w.render(Event(ev, {"value": 7}))  # a value no state maps to
    assert seen == [None, None]


def test_status_poll_reads_the_field_and_reports_errors() -> None:
    key = DIRAC_KEY
    ok = status.poll("utils", "1,1", key, fetch=lambda _url: b'{"enabled":1}')
    assert ok.data == {"value": 1}
    missing = status.poll("utils", "1,1", key, fetch=lambda _url: b'{"other":1}')
    assert "enabled" in str(missing.data["error"])

    def down(_url: str) -> bytes:
        raise OSError("connection refused")

    assert "refused" in str(status.poll("utils", "1,1", key, fetch=down).data["error"])


def test_status_maps_by_value_not_position() -> None:
    # A device that reports strings, listed in an order that does not match the values' order.
    key = (
        config.parse(
            {
                "pages": ["p"],
                "screens": {
                    "p": {
                        "kind": "page",
                        "keys": {
                            "0,1": {
                                "toggle": {
                                    "status": {"url": "http://x/api", "field": "mode"},
                                    "states": [
                                        {
                                            "label": "Eco",
                                            "value": "eco",
                                            "http": {"method": "PUT", "url": "http://x/eco"},
                                        },
                                        {
                                            "label": "Max",
                                            "value": "max",
                                            "http": {"method": "PUT", "url": "http://x/max"},
                                        },
                                    ],
                                }
                            }
                        },
                    }
                },
            }
        )
        .screens["p"]
        .keys["0,1"]
    )
    assert status.state_index(key, "max") == 1 and status.state_index(key, "eco") == 0
    assert status.state_index(key, 0) is None  # the position is not a value


def test_not_favourite_is_the_same_solid_star_in_dim_red() -> None:
    # User requests: Music's Favourite is a star now; "not favourite" is the same star, solid, in dim red.
    from hexclack.widgets.now_playing import FAVOURITE, NOT_FAVOURITE, star, star_mask

    fav, not_fav = star(True), star(False)
    assert fav.getpixel((40, 42)) == FAVOURITE and not_fav.getpixel((40, 42)) == NOT_FAVOURITE
    # Same silhouette: both are the star mask filled with one colour (compare against the mask, not a
    # brightness threshold, which would clip the dim star's anti-aliased edge).
    mask = star_mask(80)
    for image, colour in ((fav, FAVOURITE), (not_fav, NOT_FAVOURITE)):
        expected = Image.new("RGB", (80, 80), "black")
        expected.paste(Image.new("RGB", (80, 80), colour), (0, 0), mask)
        assert image.tobytes() == expected.tobytes()
    assert sum(NOT_FAVOURITE) < sum(FAVOURITE) / 4  # clearly dim


# -- press feedback (user report: the star lagged a re-queue; Play/Pause showed paused while playing) --


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def press_event(favorited: bool, track: str = "T1", **pressed: object) -> Event:
    return Event("music", {"now": NowPlaying("playing", track, "t", "a", favorited), **pressed})


def test_favourite_press_shows_at_once_and_survives_stale_reads() -> None:
    # Measured: after a favourite write Music reads back the OLD value for ~10 s.
    from hexclack.widgets.now_playing import FAVOURITE, NOT_FAVOURITE

    clock = Clock()
    w = LoveWidget(clock)
    assert w.render(press_event(False)) is not None  # not a favourite
    pressed = w.render(press_event(False, pressed_favorited=True))  # press: the read is still stale
    assert pressed is not None and pressed.getpixel((40, 42)) == FAVOURITE
    for t in (1, 5, 10):  # stale reads keep coming
        clock.t = t
        assert w.render(press_event(False)) is None  # no flip back
    clock.t = 11
    assert w.render(press_event(True)) is None  # Music caught up: same image, no redraw
    clock.t = 40
    back = w.render(press_event(False))  # a real change later (e.g. from the phone) shows again
    assert back is not None and back.getpixel((40, 42)) == NOT_FAVOURITE


def test_favourite_hold_expires_and_ends_on_track_change() -> None:
    from hexclack.widgets.now_playing import HOLD_FAVOURITE_S, NOT_FAVOURITE

    clock = Clock()
    w = LoveWidget(clock)
    w.render(press_event(False))
    w.render(press_event(False, pressed_favorited=True))
    clock.t = HOLD_FAVOURITE_S + 1  # the write never landed: show what Music says
    expired = w.render(press_event(False))
    assert expired is not None and expired.getpixel((40, 42)) == NOT_FAVOURITE
    w.render(press_event(False, pressed_favorited=True))
    skipped = w.render(press_event(False, track="T2"))  # next track: its own state, at once
    assert skipped is not None and skipped.getpixel((40, 42)) == NOT_FAVOURITE


def test_play_pause_press_shows_the_new_state_despite_a_stale_read() -> None:
    clock = Clock()
    w = NowPlayingWidget(clock)
    playing = w.render(music("playing"))
    paused_img = w.render(Event("music", {"now": NowPlaying("playing", "T1"), "pressed_state": "paused"}))
    assert playing is not None and paused_img is not None and paused_img.tobytes() != playing.tobytes()
    clock.t = 0.5
    assert w.render(music("playing")) is None  # the stale "playing" read does not undo the press
    clock.t = 1.0
    assert w.render(music("paused")) is None  # Music agrees
    clock.t = 10
    assert w.render(music("playing")) is not None  # a real later change shows


def test_transport_returns_what_it_set_not_a_read_back(monkeypatch: pytest.MonkeyPatch) -> None:
    from hexclack.music import transport

    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake(script: str, *args: str, timeout: float = 10) -> str:
        calls.append((script, args))
        if script == transport.GET_FAVORITED:
            return "false"
        if script == transport.GET_STATE:
            return "playing"
        return ""

    monkeypatch.setattr(transport, "osascript", fake)
    assert transport.toggle_favorited() is True
    assert (transport.SET_FAVORITED, ("true",)) in calls
    assert transport.play_pause() == "paused"


# -- infodisp lessons ---------------------------------------------------------------------------------


def test_status_poll_fails_closed_on_any_exception() -> None:
    # http.client.IncompleteRead is not an OSError; it used to escape and kill the poll thread.
    import http.client

    def torn(_url: str) -> bytes:
        raise http.client.IncompleteRead(b"{")

    event = status.poll("utils", "1,1", DIRAC_KEY, fetch=torn)
    assert "IncompleteRead" in str(event.data["error"])


def test_pihole_poll_fails_closed_on_any_exception() -> None:
    class Weird(PiholeClient):
        def status(self) -> dict[str, object]:
            raise RuntimeError("torn reply")

    event = pw.poll(Weird("server:8000", password=lambda: ""))
    assert "RuntimeError" in str(event.data["error"])


def test_an_older_refresh_never_publishes_over_a_newer_one() -> None:
    # Refreshes run on timer threads; a slow (older) read finishing last must be dropped.
    import threading

    gate = threading.Event()
    published: list[str] = []
    reads = iter(["old", "new"])

    def read() -> NowPlaying:
        value = next(reads)
        if value == "old":
            gate.wait(5)  # the first read is slow
        return NowPlaying("playing", value)

    def record(event: Event) -> None:
        now = event.data["now"]
        assert isinstance(now, NowPlaying)
        published.append(str(now.track_id))

    watcher = MusicWatcher(read, record)
    slow = threading.Thread(target=watcher.refresh)
    slow.start()
    while watcher._seq < 1:
        pass
    watcher.refresh()  # the newer read publishes first
    gate.set()
    slow.join(5)
    assert published == ["new"]


def test_pihole_state_line_says_pihole_on_or_off_and_fits(monkeypatch: pytest.MonkeyPatch) -> None:
    # User request: "pihole on" / "pihole off" on the Pi-hole keys.
    from PIL import ImageDraw

    from hexclack import tiles

    lines: list[str] = []

    def capture(title: str, line: str, *_a: object, **_k: object) -> Image.Image:
        lines.append(line)
        return Image.new("RGB", (80, 80))

    monkeypatch.setattr(pw, "status_tile", capture)
    w = pw.PiholeWidget("server:8000", "server")
    ev = "pihole:server:8000"
    w.render(Event(ev, {"blocking": "enabled", "timer": None, "blocked": 1}))
    w.render(Event(ev, {"blocking": "disabled", "timer": None, "blocked": 1}))
    w.render(Event(ev, {"blocking": "disabled", "timer": 3581, "blocked": 1}))
    assert lines == ["pihole on", "pihole off", "off 59:41"]
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    assert all(probe.textlength(line, font=tiles.bold(10)) + 14 <= 76 for line in lines)  # dot + text fit


def test_watcher_offers_art_to_the_saver_only_while_playing() -> None:
    # User request: the screen saver clock shows the album art behind the digits while music plays.
    states = iter(["playing", "paused", "stopped"])
    watcher = MusicWatcher(lambda: NowPlaying(next(states), "T1"), lambda _e: None, artwork=lambda _t: JPEG)
    assert watcher.playing_art() is None  # nothing read yet
    watcher.refresh()
    assert watcher.playing_art() == JPEG
    watcher.refresh()
    assert watcher.playing_art() is None  # paused: back to black
    watcher.refresh()
    assert watcher.playing_art() is None


def test_a_press_is_not_overwritten_by_an_older_refresh() -> None:
    # A refresh read before the press must not replace the pressed snapshot the saver reads.
    import threading

    gate = threading.Event()
    states = iter(["playing", "paused"])  # the slow refresh saw "playing"; the press paused

    def read() -> NowPlaying:
        state = next(states)
        if state == "playing":
            gate.wait(5)
        return NowPlaying(state, "T1")

    published: list[str] = []

    def record(event: Event) -> None:
        now = event.data["now"]
        assert isinstance(now, NowPlaying)
        published.append(now.state)

    watcher = MusicWatcher(read, record, timer=FakeTimer(), artwork=lambda _t: JPEG)  # timers never fire
    slow = threading.Thread(target=watcher.refresh)
    slow.start()
    while watcher._seq < 1:
        pass
    watcher.pressed({"state": "paused"})
    gate.set()
    slow.join(5)
    assert published == ["paused"]
    assert watcher.playing_art() is None
