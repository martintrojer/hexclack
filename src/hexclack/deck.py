"""What the deck shows and what a press does: screens, navigation, gestures and key feedback.

Pure with respect to the device: it turns key events into Draw commands (via `submit`) and action
runs (via the Runner). Navigation follows docs/design.md section 5: pages form a line (prev/next,
no wrap), a folder's 0,0 is the automatic back key to its parent.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageEnhance

from hexclack import render, tiles
from hexclack.actions import Runner
from hexclack.config import BACK_SLOT, COLS, HOME_SCREEN, ROWS, Action, Config, Key
from hexclack.device import Command, Draw
from hexclack.gestures import Gestures
from hexclack.music.bot import page_items, playlist_label, playlist_rows

log = logging.getLogger(__name__)

FLASH_S = 1.0  # how long an error tint stays (docs/music.md section 3)
POLL_S = 0.02  # gesture timer resolution
EPHEMERAL_SCREEN = "__ephemeral__"  # runtime-only; never a config screen name
BOT_LIST_SCREEN = EPHEMERAL_SCREEN  # alias for older tests/docs
EPHEMERAL_NEXT = "2,1"  # Next chrome when a page has more items
BOT_LIST_NEXT = EPHEMERAL_NEXT
# Playlist slots after Home when Next may occupy EPHEMERAL_NEXT (Mini: 4).
PLAYLIST_LIST_CAPACITY = COLS * ROWS - 2
BOT_LIST_CAPACITY = PLAYLIST_LIST_CAPACITY
# Category slots after Home + Any when Next may occupy EPHEMERAL_NEXT (Mini: 3).
CATEGORY_ANY_SLOT = "1,0"
CATEGORY_LIST_CAPACITY = COLS * ROWS - 3


def slot_of(index: int) -> str:
    return f"{index % COLS},{index // COLS}"


def index_of(slot: str) -> int:
    col, row = (int(p) for p in slot.split(","))
    return row * COLS + col


def dimmed(image: Image.Image) -> Image.Image:
    return ImageEnhance.Brightness(image).enhance(0.5)


def tinted(image: Image.Image) -> Image.Image:
    return Image.blend(image, Image.new("RGB", image.size, (200, 0, 0)), 0.55)


@dataclass(frozen=True)
class PlaylistEntry:
    name: str
    icon: str | None = None


def _playlist_entries_from_payload(payload: dict[str, object]) -> list[PlaylistEntry]:
    """Parse playlist_list.entries (preferred) or legacy playlist_list.names."""
    raw = payload.get("entries")
    if isinstance(raw, list):
        out: list[PlaylistEntry] = []
        for item in raw:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name:
                    icon = item.get("icon")
                    out.append(PlaylistEntry(name=name, icon=icon if isinstance(icon, str) and icon else None))
            elif isinstance(item, str) and item:
                out.append(PlaylistEntry(name=item))
        return out
    names = payload.get("names")
    if isinstance(names, list):
        return [PlaylistEntry(name=n) for n in names if isinstance(n, str) and n]
    return []


@dataclass
class PlaylistListSession:
    label: str
    entries: tuple[PlaylistEntry, ...]
    dated: bool = False
    page: int = 0

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(e.name for e in self.entries)


@dataclass
class CategoryListSession:
    label: str
    groups: dict[str, tuple[str, ...]]
    categories: tuple[str, ...]
    page: int = 0


# Back-compat name used by bot list tests.
BotListSession = PlaylistListSession


class Deck:
    def __init__(
        self,
        cfg: Config,
        base: Path,
        submit: Callable[[Command], None],
        runner_factory: Callable[[Callable[[str, int, bool], None]], Runner],
        clock: Callable[[], float] = time.monotonic,
        widget_image: Callable[[str, int], Image.Image | None] = lambda _screen, _index: None,
        alert_severity: Callable[[], int] = lambda: 0,
    ) -> None:
        self.cfg = cfg
        self.base = base
        self.submit = submit
        self.clock = clock
        self.widget_image = widget_image  # the latest live image of a widget key, if it has drawn yet
        self.alert_severity = alert_severity  # worst current alert (0 none), for keys with alerts = true
        self.home = HOME_SCREEN if HOME_SCREEN in cfg.screens else cfg.pages[0]
        self.screen = self.home
        self.gestures = Gestures(cfg.gestures.double_ms, cfg.gestures.hold_ms)
        self.runner = runner_factory(self._done)
        self._images: dict[tuple[str, str], Image.Image] = {}
        self._lock = threading.Lock()
        self.asleep = False
        self.playlist_list: PlaylistListSession | None = None
        self.category_list: CategoryListSession | None = None
        self.bot_list_capacity = PLAYLIST_LIST_CAPACITY
        self.category_list_capacity = CATEGORY_LIST_CAPACITY

    @property
    def bot_list(self) -> PlaylistListSession | None:
        """Dated Bot list session, if that is what the ephemeral screen is showing."""
        session = self.playlist_list
        return session if session is not None and session.dated else None

    @bot_list.setter
    def bot_list(self, value: PlaylistListSession | None) -> None:
        self.playlist_list = value

    # -- drawing -----------------------------------------------------------------------------

    def _keys(self, screen: str) -> dict[str, Key]:
        if screen == EPHEMERAL_SCREEN:
            if self.playlist_list is not None:
                return self._playlist_list_keys()
            if self.category_list is not None:
                return self._category_list_keys()
            return {}
        return self.cfg.screens[screen].keys

    def image(self, screen: str, slot: str) -> Image.Image:
        """The current image of a slot, with the alert border on keys that ask for it."""
        image = self._base_image(screen, slot)
        key = self._keys(screen).get(slot)
        if key is not None and key.alerts:
            return render.alert_border(image, self.alert_severity())
        return image

    def alerts_changed(self) -> None:
        """Redraw the visible keys that show the alert border."""
        if self.asleep:
            return
        for slot, key in self._keys(self.screen).items():
            if key.alerts:
                self.submit(Draw(index_of(slot), self.image(self.screen, slot)))

    def _base_image(self, screen: str, slot: str) -> Image.Image:
        """Static images cached; a toggle shows its current state; a widget its latest image."""
        key = self._keys(screen).get(slot)
        if screen == EPHEMERAL_SCREEN:
            cache_key = (screen, slot)
            if cache_key not in self._images:
                self._images[cache_key] = self._ephemeral_image(key)
            return self._images[cache_key]
        s = self.cfg.screens[screen]
        if key is not None and (key.widget or key.toggle_status is not None):
            live = self.widget_image(screen, index_of(slot))
            if live is not None:
                return live
        if key is not None and key.toggle:
            index = self.runner.toggle_state(screen, index_of(slot), key)
            state = key.toggle[index]
            return render.key_image(Key(slot=slot, title=state.label, icon=state.icon), self.base)
        cache_key = (screen, slot)
        if cache_key not in self._images:
            self._images[cache_key] = render.screen_images(s, self.base)[slot]
        return self._images[cache_key]

    def draw_screen(self) -> None:
        for row in range(ROWS):
            for col in range(COLS):
                slot = f"{col},{row}"
                self.submit(Draw(index_of(slot), self.image(self.screen, slot)))

    def widget_drew(self, screen: str, index: int, image: Image.Image) -> None:
        """A widget has a new image: show it if its screen is visible and its key is not mid-press."""
        if screen == self.screen and not self.asleep and not self.runner.busy(screen, index):
            key = self._keys(screen).get(slot_of(index))
            self.submit(Draw(index, render.alert_border(image, self.alert_severity()) if key and key.alerts else image))
        # If the key was busy, _done() redraws it from widget_image(), which already holds this image.

    def blank(self) -> None:
        black = Image.new("RGB", (render.KEY_SIZE, render.KEY_SIZE), "black")
        for i in range(ROWS * COLS):
            self.submit(Draw(i, black))

    # -- ephemeral lists (playlists / categories) --------------------------------------------

    def _ephemeral_image(self, key: Key | None) -> Image.Image:
        if key is None:
            return Image.new("RGB", (render.KEY_SIZE, render.KEY_SIZE), "black")
        if (
            self.playlist_list is not None
            and self.playlist_list.dated
            and key.action is not None
            and key.action.fields.get("action") == "playlist"
        ):
            rows = playlist_rows(str(key.action.fields["name"]))
            if rows is not None:
                extra, day, year = rows
                return tiles.cached(
                    {"kind": "playlist_rows", "extra": extra, "day": day, "year": year},
                    render.KEY_SIZE,
                    lambda: tiles.playlist_tile(extra, day, year),
                )
        return render.key_image(key, self.base)

    def _playlist_list_keys(self) -> dict[str, Key]:
        assert self.playlist_list is not None
        entries = list(self.playlist_list.entries)
        items, has_next = page_items(entries, self.playlist_list.page, self.bot_list_capacity)
        keys: dict[str, Key] = {
            BACK_SLOT: Key(slot=BACK_SLOT, action=Action(kind="nav", fields={"home": True})),
        }
        playlist_slots = [slot_of(i) for i in range(1, COLS * ROWS) if not (has_next and slot_of(i) == EPHEMERAL_NEXT)]
        dated = self.playlist_list.dated
        for slot, entry in zip(playlist_slots, items, strict=False):
            # Icon-only when artwork is supplied (often already labeled); else a text title.
            if entry.icon:
                title = None
            elif dated:
                title = playlist_label(entry.name)
            else:
                title = entry.name
            keys[slot] = Key(
                slot=slot,
                title=title,
                icon=entry.icon,
                action=Action(kind="music", fields={"action": "playlist", "name": entry.name}),
            )
        if has_next:
            keys[EPHEMERAL_NEXT] = Key(
                slot=EPHEMERAL_NEXT,
                title="Next",
                action=Action(kind="nav", fields={"ephemeral_next": True}),
            )
        return keys

    def _bot_list_keys(self) -> dict[str, Key]:
        return self._playlist_list_keys()

    def _category_list_keys(self) -> dict[str, Key]:
        assert self.category_list is not None
        categories = list(self.category_list.categories)
        items, has_next = page_items(categories, self.category_list.page, self.category_list_capacity)
        all_names = [n for cat in self.category_list.categories for n in self.category_list.groups[cat]]
        keys: dict[str, Key] = {
            BACK_SLOT: Key(slot=BACK_SLOT, action=Action(kind="nav", fields={"home": True})),
            CATEGORY_ANY_SLOT: Key(
                slot=CATEGORY_ANY_SLOT,
                title="Any",
                action=Action(kind="music", fields={"action": "random_playlist", "names": all_names}),
            ),
        }
        cat_slots = [slot_of(i) for i in range(2, COLS * ROWS) if not (has_next and slot_of(i) == EPHEMERAL_NEXT)]
        for slot, category in zip(cat_slots, items, strict=False):
            names = list(self.category_list.groups[category])
            keys[slot] = Key(
                slot=slot,
                title=category,
                action=Action(kind="music", fields={"action": "random_playlist", "names": names}),
            )
        if has_next:
            keys[EPHEMERAL_NEXT] = Key(
                slot=EPHEMERAL_NEXT,
                title="Next",
                action=Action(kind="nav", fields={"ephemeral_next": True}),
            )
        return keys

    def _clear_ephemeral_images(self) -> None:
        self._images = {k: v for k, v in self._images.items() if k[0] != EPHEMERAL_SCREEN}

    def _clear_ephemeral(self) -> None:
        self.playlist_list = None
        self.category_list = None

    def open_playlist_list(
        self,
        label: str,
        entries: list[PlaylistEntry] | list[str],
        *,
        dated: bool = False,
    ) -> None:
        """Show an in-memory playlist folder. No-op if entries is empty."""
        packed: list[PlaylistEntry] = []
        for e in entries:
            if isinstance(e, PlaylistEntry):
                if e.name:
                    packed.append(e)
            elif e:
                packed.append(PlaylistEntry(name=e))
        if not packed:
            return
        self._clear_ephemeral()
        self.playlist_list = PlaylistListSession(label=label, entries=tuple(packed), dated=dated, page=0)
        self._clear_ephemeral_images()
        self.go(EPHEMERAL_SCREEN)

    def open_bot_list(self, category: str, names: list[str]) -> None:
        """Show dated Bot playlists for category (wrapper around open_playlist_list)."""
        self.open_playlist_list(category, names, dated=True)

    def open_category_list(self, label: str, groups: dict[str, list[str]], order: list[str]) -> None:
        """Show top-level folder categories for explore/saved. No-op if order is empty."""
        if not order:
            return
        packed = {cat: tuple(names) for cat in order if (names := groups.get(cat))}
        if not packed:
            return
        self._clear_ephemeral()
        self.category_list = CategoryListSession(label=label, groups=packed, categories=tuple(packed), page=0)
        self._clear_ephemeral_images()
        self.go(EPHEMERAL_SCREEN)

    def ephemeral_next_page(self) -> None:
        if self.playlist_list is not None:
            _items, has_next = page_items(
                list(self.playlist_list.names), self.playlist_list.page, self.bot_list_capacity
            )
            if not has_next:
                return
            self.playlist_list = PlaylistListSession(
                label=self.playlist_list.label,
                entries=self.playlist_list.entries,
                dated=self.playlist_list.dated,
                page=self.playlist_list.page + 1,
            )
        elif self.category_list is not None:
            _items, has_next = page_items(
                list(self.category_list.categories), self.category_list.page, self.category_list_capacity
            )
            if not has_next:
                return
            self.category_list = CategoryListSession(
                label=self.category_list.label,
                groups=self.category_list.groups,
                categories=self.category_list.categories,
                page=self.category_list.page + 1,
            )
        else:
            return
        self._clear_ephemeral_images()
        self.gestures.reset()
        self.draw_screen()

    def bot_list_next_page(self) -> None:
        self.ephemeral_next_page()

    def handle_music_changed(self, _screen: str, _index: int, changed: dict[str, object]) -> None:
        """Open ephemeral lists from music action payloads; ignore other keys."""
        playlist = changed.get("playlist_list")
        if isinstance(playlist, dict):
            label = playlist.get("label")
            dated = bool(playlist.get("dated", False))
            if not isinstance(label, str):
                return
            entries = _playlist_entries_from_payload(playlist)
            if entries:
                self.open_playlist_list(label, entries, dated=dated)
            return
        # Older bot_list payload shape (category + names).
        legacy = changed.get("bot_list")
        if isinstance(legacy, dict):
            category = legacy.get("category")
            names = legacy.get("names")
            if isinstance(category, str) and isinstance(names, list):
                self.open_bot_list(category, [n for n in names if isinstance(n, str)])
            return
        category_payload = changed.get("category_list")
        if isinstance(category_payload, dict):
            label = category_payload.get("label")
            groups_raw = category_payload.get("groups")
            order = category_payload.get("order")
            if isinstance(label, str) and isinstance(groups_raw, dict) and isinstance(order, list):
                groups = {
                    str(k): [n for n in v if isinstance(n, str)] for k, v in groups_raw.items() if isinstance(v, list)
                }
                self.open_category_list(label, groups, [c for c in order if isinstance(c, str)])

    # -- navigation --------------------------------------------------------------------------

    def go(self, screen: str) -> None:
        log.info("screen %s -> %s", self.screen, screen)
        if screen != EPHEMERAL_SCREEN:
            self._clear_ephemeral()
        self.screen = screen
        self.gestures.reset()
        self.draw_screen()

    def nav(self, fields: dict[str, object]) -> None:
        if fields.get("home"):
            self.go_home()
            return
        if fields.get("ephemeral_next") or fields.get("bot_list_next"):
            self.ephemeral_next_page()
            return
        if "folder" in fields:
            self.go(str(fields["folder"]))
            return
        page = self.screen
        while page != EPHEMERAL_SCREEN and self.cfg.screens[page].kind == "folder":
            page = self.cfg.screens[page].parent or self.cfg.pages[0]
        if page == EPHEMERAL_SCREEN:
            return
        i = self.cfg.pages.index(page)
        step = 1 if fields.get("page") == "next" else -1
        j = i + step
        if 0 <= j < len(self.cfg.pages):  # pages form a line: no wrap
            self.go(self.cfg.pages[j])

    def go_home(self) -> None:
        """One press from any screen, at any depth (user request: no step-by-step back)."""
        self._clear_ephemeral()
        if self.screen != self.home:
            self.go(self.home)

    # -- presses -----------------------------------------------------------------------------

    def _gestures_of(self, key: Key | None) -> set[str]:
        if key is None:
            return set()
        if key.gestures:
            return set(key.gestures)
        return {"tap"}

    def on_key(self, index: int, pressed: bool) -> None:
        """From the library read thread: keep it quick (no device calls, no actions run here)."""
        with self._lock:
            slot = slot_of(index)
            if self.screen != EPHEMERAL_SCREEN:
                screen = self.cfg.screens[self.screen]
                if screen.kind == "folder" and slot == BACK_SLOT:
                    if not pressed:
                        self.go_home()
                    return
            keys = self._keys(self.screen)
            key = keys.get(slot)
            if pressed and key is not None and (key.action or key.gestures or key.toggle):
                self.submit(Draw(index, dimmed(self.image(self.screen, slot))))
            for gesture in self.gestures.event(index, pressed, self.clock(), self._gestures_of(key)):
                self._fire(index, key, gesture)
            if not pressed and key is not None and not self.runner.busy(self.screen, index):
                self.submit(Draw(index, self.image(self.screen, slot)))  # undim; a running action undims on done

    def poll(self) -> None:
        """From the tick thread every POLL_S: timer-driven gestures (hold, delayed tap)."""
        with self._lock:
            keys = self._keys(self.screen)
            has = {index_of(s): self._gestures_of(k) for s, k in keys.items()}
            for index, gesture in self.gestures.poll(self.clock(), has):
                self._fire(index, keys.get(slot_of(index)), gesture)

    def _fire(self, index: int, key: Key | None, gesture: str) -> None:
        if key is None:
            return
        action: Action | None = key.gestures.get(gesture) if key.gestures else key.action
        log.info("%s %s %s", self.screen, slot_of(index), gesture)
        if action is not None and action.kind == "nav":
            self.nav(action.fields)
            return
        if action is not None or key.toggle:
            self.runner.submit(self.screen, index, key, action)

    def _done(self, screen: str, index: int, ok: bool) -> None:
        """From a worker: restore the key, or flash it red for FLASH_S on failure."""
        if screen != self.screen or self.asleep:  # the screen saver owns the keys
            return
        slot = slot_of(index)
        normal = self.image(screen, slot)  # a widget key: the newest widget image, not a stale copy
        if ok:
            self.submit(Draw(index, normal))
            return
        self.submit(Draw(index, tinted(normal)))

        def restore() -> None:
            if self.screen == screen:
                self.submit(Draw(index, self.image(screen, slot)))

        threading.Timer(FLASH_S, restore).start()
