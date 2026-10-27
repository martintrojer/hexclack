"""Favourites playlist list and Curated/Mine category ephemeral screens."""

from pathlib import Path

from hexclack import config
from hexclack.actions import Runner
from hexclack.config import Action, Key
from hexclack.deck import CATEGORY_ANY_SLOT, EPHEMERAL_NEXT, EPHEMERAL_SCREEN, Deck, index_of
from hexclack.music import browse
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


def test_favourites_payload_opens_plain_titles() -> None:
    h = Harness()
    h.deck.go("music")
    h.deck.handle_music_changed(
        "music",
        2,
        {
            "playlist_list": {
                "label": "Favourites",
                "entries": [{"name": "Flow State"}, {"name": "New Music"}],
                "dated": False,
            }
        },
    )
    assert h.deck.screen == EPHEMERAL_SCREEN
    keys = h.deck._playlist_list_keys()
    assert keys["1,0"].title == "Flow State"
    assert keys["1,0"].action is not None
    assert keys["1,0"].action.fields == {"action": "playlist", "name": "Flow State"}


def test_favourites_with_tile_keeps_title() -> None:
    h = Harness()
    h.deck.go("music")
    h.deck.handle_music_changed(
        "music",
        2,
        {
            "playlist_list": {
                "label": "Favourites",
                "entries": [
                    {
                        "name": "Flow State",
                        "tile": {"glyph": "🌊", "start": "#0a84ff", "end": "#002a5c"},
                    }
                ],
                "dated": False,
            }
        },
    )
    keys = h.deck._playlist_list_keys()
    assert keys["1,0"].title == "Flow State"
    assert keys["1,0"].tile is not None
    assert keys["1,0"].tile.glyph == "🌊"
    assert keys["1,0"].icon is None


def test_favourites_with_icon_skips_title() -> None:
    h = Harness()
    h.deck.go("music")
    h.deck.handle_music_changed(
        "music",
        2,
        {
            "playlist_list": {
                "label": "Favourites",
                "entries": [{"name": "Flow State", "icon": "icons/tile.png"}],
                "dated": False,
            }
        },
    )
    keys = h.deck._playlist_list_keys()
    assert keys["1,0"].title is None
    assert keys["1,0"].icon == "icons/tile.png"
    assert keys["1,0"].action is not None
    assert keys["1,0"].action.fields["name"] == "Flow State"


def test_category_list_shows_pre_picked_playlist_names(monkeypatch) -> None:
    h = Harness()
    h.deck.go("music")
    # open_category_list: one pick per category (order), then Any from the flat pool.
    picks = iter(
        [
            browse.PlaylistRef("Canon/Essentials", "A"),
            browse.PlaylistRef("Lanes/Work", "C"),
            browse.PlaylistRef("Canon/Warp", "B"),
        ]
    )

    def choose(seq: list) -> object:
        return next(picks)

    monkeypatch.setattr("hexclack.deck.random.choice", choose)
    h.deck.handle_music_changed(
        "music",
        5,
        {
            "category_list": {
                "label": "Curated",
                "groups": {
                    "Canon": [
                        {"name": "A", "folder": "Canon/Essentials"},
                        {"name": "B", "folder": "Canon/Warp"},
                    ],
                    "Lanes": [{"name": "C", "folder": "Lanes/Work"}],
                },
                "order": ["Canon", "Lanes"],
            }
        },
    )
    keys = h.deck._category_list_keys()
    any_key = keys[CATEGORY_ANY_SLOT]
    assert any_key.action is not None
    assert any_key.action.fields == {
        "action": "playlist",
        "name": "B",
        "folder": "Canon/Warp",
        "category": "Any",
    }
    canon = keys["2,0"]
    assert canon.action is not None
    assert canon.action.fields == {
        "action": "playlist",
        "name": "A",
        "folder": "Canon/Essentials",
        "category": "Canon",
    }
    lanes = keys["0,1"]
    assert lanes.action is not None
    assert lanes.action.fields == {
        "action": "playlist",
        "name": "C",
        "folder": "Lanes/Work",
        "category": "Lanes",
    }
    # Tile shows playlist name with category under it; colour from session palette.
    img = h.deck._ephemeral_image(canon)
    from hexclack import tiles

    assert h.deck.category_list is not None
    bg = h.deck.category_list.colors["Canon"]
    assert img.tobytes() == tiles.pick_tile("A", "Canon", bg=bg).tobytes()


def test_category_next_then_home() -> None:
    from hexclack.music.browse import PlaylistRef

    h = Harness()
    order = [f"Cat{i}" for i in range(8)]
    groups = {c: [PlaylistRef(folder=c, name=c)] for c in order}
    h.deck.open_category_list("Curated", groups, order)
    page0 = h.deck._category_list_keys()
    assert EPHEMERAL_NEXT in page0
    assert CATEGORY_ANY_SLOT in page0
    h.tap(EPHEMERAL_NEXT)
    assert h.deck.category_list is not None
    assert h.deck.category_list.page == 1
    page1 = h.deck._category_list_keys()
    assert all(k.action is None or k.action.fields.get("category") != "Any" for k in page1.values())
    h.tap("0,0")
    assert h.deck.screen == "home"
    assert h.deck.category_list is None


def test_config_bakes_favourites_and_explore_filters() -> None:
    fav = CFG.screens["music"].keys["2,0"].action
    assert fav is not None
    assert fav.fields["action"] == "favourites"
    assert fav.fields["entries"] == [
        {"name": "Sample Favourite 1"},
        {"name": "Sample Favourite 2"},
        {"name": "Sample Favourite 3"},
    ]
    explore = CFG.screens["music"].keys["2,1"].action
    assert explore is not None
    assert explore.fields["action"] == "explore"
    assert explore.fields["source"] == "curated"
    assert "Demo" in explore.fields["blacklist_folders"]
    assert "Now/History" in explore.fields["blacklist_folders"]
    assert "New Music" in explore.fields["blacklist_names"]
    saved = CFG.screens["music"].keys["0,1"].action
    assert saved is not None
    assert saved.fields["source"] == "saved"
    assert "Bot" in saved.fields["blacklist_folders"]
