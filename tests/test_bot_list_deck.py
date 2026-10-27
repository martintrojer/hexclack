"""Ephemeral Bot playlist list screen on the Deck."""

from pathlib import Path

from hexclack import config, render, tiles
from hexclack.actions import Runner
from hexclack.config import Action, Key
from hexclack.deck import BOT_LIST_NEXT, BOT_LIST_SCREEN, Deck, index_of
from hexclack.pihole import PiholeClient

ROOT = Path(__file__).parent.parent
CFG = config.load(ROOT / "tests/data/layout.toml")

NAMES = [
    "Jazz 2026 October 24",
    "Jazz 2026 October 17",
    "Jazz 2026 October 10",
    "Jazz 2026 October 3",
    "Jazz 2026 September 26",
    "Jazz 2026 September 19",
]


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


def test_open_bot_list_shows_labels_newest_first() -> None:
    h = Harness()
    h.deck.open_bot_list("Jazz", NAMES)
    assert h.deck.screen == BOT_LIST_SCREEN
    keys = h.deck._bot_list_keys()
    assert keys["1,0"].title == "2026 Oct 24"
    assert keys["1,0"].action is not None
    assert keys["1,0"].action.fields["name"] == "Jazz 2026 October 24"
    assert "Next" in {k.title for k in keys.values()}
    # Shuffled per-open tints (same helper as Mine/Curated).
    assert h.deck.playlist_list is not None
    assert set(h.deck.playlist_list.colors) == set(NAMES)


def test_open_bot_list_label_includes_extra() -> None:
    h = Harness()
    h.deck.open_bot_list("Jazz", ["Jazz DNA 2026 September 28", "Jazz 2026 October 1"])
    keys = h.deck._bot_list_keys()
    assert keys["1,0"].title == "DNA 2026 Sep 28"
    assert keys["2,0"].title == "2026 Oct 1"


def test_next_key_uses_nav_chevron_glyph() -> None:
    key = Key(
        slot=BOT_LIST_NEXT,
        title="Next",
        action=Action(kind="nav", fields={"bot_list_next": True}),
    )
    got = render.key_image(key, ROOT / "tests/data")
    expected = render.overlay_title(tiles.render_nav("right"), "Next")
    assert got.tobytes() == expected.tobytes()


def test_five_names_no_next() -> None:
    h = Harness()
    h.deck.open_bot_list("Jazz", NAMES[:5])
    keys = h.deck._bot_list_keys()
    assert keys[BOT_LIST_NEXT].title != "Next"
    action = keys[BOT_LIST_NEXT].action
    assert action is not None
    assert action.fields.get("action") == "playlist"


def test_next_pages_then_home_clears() -> None:
    h = Harness()
    h.deck.open_bot_list("Jazz", NAMES)
    h.tap(BOT_LIST_NEXT)
    assert h.deck.bot_list is not None
    assert h.deck.bot_list.page == 1
    keys = h.deck._bot_list_keys()
    assert keys["1,0"].action is not None
    assert keys["1,0"].action.fields["name"] == "Jazz 2026 September 26"
    h.tap("0,0")
    assert h.deck.screen == "home"
    assert h.deck.bot_list is None


def test_playlist_tap_plays_full_name() -> None:
    h = Harness()
    h.deck.open_bot_list("Jazz", NAMES[:3])
    h.tap("1,0")
    assert h.ran == [{"action": "playlist", "name": "Jazz 2026 October 24"}]


def test_handle_music_changed_opens_list() -> None:
    h = Harness()
    h.deck.handle_music_changed(
        "bot",
        0,
        {
            "playlist_list": {
                "label": "Jazz",
                "entries": [{"name": n} for n in NAMES[:2]],
                "dated": True,
            }
        },
    )
    assert h.deck.screen == BOT_LIST_SCREEN
    assert h.deck.bot_list is not None
    assert h.deck.bot_list.label == "Jazz"


def test_handle_music_changed_ignores_other_payloads() -> None:
    h = Harness()
    h.deck.go("bot")
    h.deck.handle_music_changed("bot", 0, {"favorited": True})
    assert h.deck.screen == "bot"
    assert h.deck.bot_list is None


def test_open_bot_list_empty_does_not_navigate() -> None:
    h = Harness()
    h.deck.go("bot")
    h.deck.open_bot_list("Jazz", [])
    assert h.deck.screen == "bot"
    assert h.deck.bot_list is None
