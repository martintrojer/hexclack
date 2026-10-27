"""Navigation and gesture dispatch on the real layout. A wrong target means the user presses a key
and lands somewhere unexpected, with no error (layout.md: top-left always leads towards home)."""

import io
from pathlib import Path

from PIL import Image

from hexclack import config, render
from hexclack.actions import Runner
from hexclack.config import Action, Key
from hexclack.deck import Deck, index_of
from hexclack.device import Draw
from hexclack.pihole import PiholeClient

ROOT = Path(__file__).parent.parent
CFG = config.load(ROOT / "tests/data/layout.toml")


def no_pihole(host: str) -> PiholeClient:
    raise AssertionError(host)


class StubRunner(Runner):
    def __init__(self, ran: list[dict[str, object]]) -> None:
        super().__init__(pihole=no_pihole)
        self.ran = ran

    def submit(self, screen: str, index: int, key: Key, action: Action | None) -> bool:
        self.ran.append(action.fields if action else {"toggle": True})
        return True


class Harness:
    def __init__(self) -> None:
        self.t = 0.0
        self.ran: list[dict[str, object]] = []
        self.deck = Deck(
            CFG, ROOT / "tests/data", lambda _c: None, lambda _d: StubRunner(self.ran), clock=lambda: self.t
        )

    def tap(self, slot: str, hold: float = 0.05) -> None:
        i = index_of(slot)
        self.deck.on_key(i, True)
        self.t += hold
        self.deck.on_key(i, False)
        self.t += 0.5
        self.deck.poll()

    def hold(self, slot: str) -> None:
        i = index_of(slot)
        self.deck.on_key(i, True)
        self.t += 0.6
        self.deck.poll()
        self.deck.on_key(i, False)


def test_starts_on_home() -> None:
    assert Harness().deck.screen == "home"


def test_one_top_left_press_goes_home_from_every_screen() -> None:
    # User request: every back key is a Home key, one press at any depth.
    h = Harness()
    for start in CFG.screens:
        if start == "home":
            continue
        h.deck.go(start)
        h.tap("0,0")
        assert h.deck.screen == "home", f"top-left on {start} went to {h.deck.screen}"


def test_pages_form_a_line_without_wrap() -> None:
    h = Harness()
    h.tap("2,0")  # home: next page
    assert h.deck.screen == "music"
    h.deck.go("home")
    h.tap("0,0")  # home's own top-left is the Utils page key, not a Home key
    assert h.deck.screen == "utils"
    h.deck.nav({"page": "prev"})  # utils is the first page: no wrap to music
    assert h.deck.screen == "utils"
    h.deck.go("music")
    h.deck.nav({"page": "next"})  # music is the last page
    assert h.deck.screen == "music"


def test_page_nav_from_a_folder_moves_from_its_page() -> None:
    h = Harness()
    h.deck.go("jazz")  # stations > jazz, under the music page
    h.deck.nav({"page": "prev"})
    assert h.deck.screen == "home"


def test_folder_keys_open_folders_and_back_returns() -> None:
    h = Harness()
    h.deck.go("music")
    h.tap("1,1")
    assert h.deck.screen == "bot"
    h.tap("2,1")
    assert h.deck.screen == "more"
    h.tap("0,0")  # three levels deep: one press home
    assert h.deck.screen == "home"


def test_bot_key_tap_is_latest_and_hold_is_shuffle() -> None:
    h = Harness()
    h.deck.go("bot")
    h.tap("1,0")
    h.hold("1,0")
    assert h.ran == [
        {"action": "bot", "category": "Beats", "mode": "latest"},
        {"action": "bot", "category": "Beats", "mode": "shuffle"},
    ]


def test_bot_key_double_is_list() -> None:
    h = Harness()
    h.deck.go("bot")
    i = index_of("1,0")
    for _ in range(2):
        h.deck.on_key(i, True)
        h.t += 0.05
        h.deck.on_key(i, False)
        h.t += 0.1
    h.t += 0.5
    h.deck.poll()
    assert h.ran == [{"action": "bot", "category": "Beats", "mode": "list"}]


def test_skip_tap_double_hold() -> None:
    h = Harness()
    h.tap("2,1")
    i = index_of("2,1")
    for _ in range(2):
        h.deck.on_key(i, True)
        h.t += 0.05
        h.deck.on_key(i, False)
        h.t += 0.1
    h.t += 0.5
    h.deck.poll()
    h.hold("2,1")
    assert [r["action"] for r in h.ran] == ["next", "previous", "shuffle"]


def test_screen_change_drops_a_pending_tap() -> None:
    h = Harness()
    i = index_of("2,1")  # Skip waits double_ms before tapping
    h.deck.on_key(i, True)
    h.deck.on_key(i, False)
    h.deck.go("bot")  # bot 2,1 is the More folder: a leaked tap would open it
    h.t += 1
    h.deck.poll()
    assert h.ran == [] and h.deck.screen == "bot"


def test_every_top_left_key_is_the_same_home_icon() -> None:
    # User request: one Home icon on every screen's top-left. Home's own 0,0 is the Utils picture.
    from hexclack import render

    home_icon = render.home_key().tobytes()
    for name, screen in CFG.screens.items():
        if name == "home":
            continue
        image = render.screen_images(screen, ROOT / "tests/data")["0,0"]
        assert image.tobytes() == home_icon, f"{name} 0,0 is not the Home icon"


def test_clock_fills_the_deck_with_one_picture() -> None:
    from hexclack import render

    keys = render.clock_keys("13:47")
    assert sorted(keys) == [0, 1, 2, 3, 4, 5]
    assert all(im.size == (80, 80) for im in keys.values())
    # The digits span the deck: every key has some white digit pixels on it.
    for i, image in keys.items():
        assert image.convert("L").point(lambda v: 255 if v > 200 else 0).getbbox() is not None, f"key {i} blank"


def test_clock_digits_span_most_of_the_deck() -> None:
    # User request: the digits fill the area, not a thin line across the middle.
    from PIL import Image

    from hexclack import render

    keys = render.clock_keys("13:47")
    deck = Image.new("L", (240, 160))
    for i, image in keys.items():
        deck.paste(image.convert("L"), ((i % 3) * 80, (i // 3) * 80))
    box = deck.point(lambda v: 255 if v > 128 else 0).getbbox()
    assert box is not None
    left, top, right, bottom = box
    assert bottom - top >= 0.85 * 160 and right - left >= 0.85 * 240


def test_clock_colour_changes_visibly_every_minute() -> None:
    # User reports: cycle Mocha accents once a minute, and make each change visible.
    import colorsys

    from hexclack import render

    def hue(colour: str) -> float:
        r, g, b = (int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
        return colorsys.rgb_to_hls(r, g, b)[0] * 360

    cycle = [render.clock_colour(m) for m in range(len(render.CLOCK_CYCLE))]
    assert set(cycle) <= set(render.MOCHA_ACCENTS) and len(set(cycle)) == len(cycle)
    for m in range(24 * 60):  # every minute change across a day, including the wrap at midnight
        a, b = hue(render.clock_colour(m)), hue(render.clock_colour((m + 1) % (24 * 60)))
        assert min(abs(a - b), 360 - abs(a - b)) >= 90, f"minute {m}: too similar"
    keys = render.clock_keys("13:47", colour=render.clock_colour(0))  # red
    used = {c for image in keys.values() for _n, c in (image.getcolors(maxcolors=80 * 80) or [])}
    assert (0xF3, 0x8B, 0xA8) in used and (255, 255, 255) not in used


def test_nested_folder_keys_carry_edge_arrows() -> None:
    # Chevron only on folder screens (deeper nav). Page-level folder keys (Stations, Bot) stay clean.
    from hexclack import render, tiles

    nested = [
        (name, slot, key)
        for name, screen in CFG.screens.items()
        if screen.kind == "folder"
        for slot, key in screen.keys.items()
        if render.opens_folder(key)
    ]
    assert len(nested) == 3  # stations: jazz, beats; bot: more
    for name, slot, key in nested:
        image = render.key_image(key, ROOT / "tests/data", folder_chevron=True)
        plain = render.icon_image(ROOT / "tests/data" / str(key.icon))
        if key.title:
            plain = render.overlay_title(plain, key.title)
        arrow = render.arrow_for(slot)
        assert image.tobytes() == tiles.add_chevron(plain, arrow).tobytes(), f"{name} {slot} has no {arrow} arrow"
    # Music page Stations/Bot open folders but draw without a chevron.
    for slot in ("1,0", "1,1"):
        key = CFG.screens["music"].keys[slot]
        assert render.opens_folder(key)
        image = render.screen_images(CFG.screens["music"], ROOT / "tests/data")[slot]
        plain = render.icon_image(ROOT / "tests/data" / str(key.icon))
        if key.title:
            plain = render.overlay_title(plain, key.title)
        assert image.tobytes() == plain.tobytes(), f"music {slot} should have no chevron"


def test_arrow_points_at_the_keys_own_edge() -> None:
    # User rule: top row left, up, right; bottom row left, down, right.
    from hexclack import render

    grid = [[render.arrow_for(f"{c},{r}") for c in range(3)] for r in range(2)]
    assert grid == [["left", "up", "right"], ["left", "down", "right"]]


def test_overlay_title_band_lets_icon_show_through() -> None:
    base = Image.new("RGB", (80, 80), (200, 100, 50))
    out = render.overlay_title(base, "Hi")
    # Bottom band is translucent black, not opaque — original hue still visible.
    pixel = out.getpixel((40, 72))
    assert isinstance(pixel, tuple)
    r, g, b = pixel[0], pixel[1], pixel[2]
    assert r > 80 and g > 30 and b > 10
    assert (r, g, b) != (200, 100, 50)  # veiled, not untouched


def _border_deck(severity: list[int]) -> tuple[Deck, list[object]]:
    drawn: list[object] = []
    deck = Deck(
        CFG,
        ROOT / "tests/data",
        drawn.append,
        lambda _d: StubRunner([]),
        alert_severity=lambda: severity[0],
    )
    return deck, drawn


def _edge(image) -> tuple[int, int, int]:
    return image.convert("RGB").getpixel((1, image.height // 2))


def test_systems_key_gets_the_screen_saver_alert_colour() -> None:
    """User request: the home page's systems (Utils) key shows the screen saver's alert colour,
    orange for a warning and red for a fault, and nothing when all is well."""
    from hexclack.render import ALERT_COLOURS

    severity = [0]
    deck, _ = _border_deck(severity)
    plain = _edge(deck.image("home", "0,0"))
    assert plain not in ALERT_COLOURS.values()
    for level in (1, 2):
        severity[0] = level
        assert _edge(deck.image("home", "0,0")) == ALERT_COLOURS[level]
    assert _edge(deck.image("home", "1,0")) not in ALERT_COLOURS.values()  # only keys with alerts = true


def test_alert_change_redraws_only_the_border_keys() -> None:
    severity = [2]
    deck, drawn = _border_deck(severity)
    deck.alerts_changed()
    assert [c.key for c in drawn if isinstance(c, Draw)] == [index_of("0,0")]
    drawn.clear()
    deck.asleep = True  # the screen saver owns the keys
    deck.alerts_changed()
    assert drawn == []


def test_clock_draws_album_art_behind_the_digits() -> None:
    # User request: while playing, the album art replaces the black background, dimmed under the digits,
    # zoomed only part way: a square cover keeps narrow black side bars rather than losing half its height.
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), (0, 0, 255)).save(buf, "JPEG")
    keys = render.clock_keys("13:47", colour="#f38ba8", background=buf.getvalue())
    top = keys[0].getpixel((40, 1))
    assert isinstance(top, tuple) and 60 < top[2] < 140  # blue, dimmed
    assert keys[0].getpixel((1, 40)) == (0, 0, 0)  # side bar


def test_clock_with_unreadable_art_is_the_plain_clock() -> None:
    plain = render.clock_keys("13:47", colour="#f38ba8")
    bad = render.clock_keys("13:47", colour="#f38ba8", background=b"not an image")
    assert all(bad[i].tobytes() == plain[i].tobytes() for i in plain)  # bold digits, no outline
