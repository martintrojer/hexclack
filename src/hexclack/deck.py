"""What the deck shows and what a press does: screens, navigation, gestures and key feedback.

Pure with respect to the device: it turns key events into Draw commands (via `submit`) and action
runs (via the Runner). Navigation follows docs/design.md section 5: pages form a line (prev/next,
no wrap), a folder's 0,0 is the automatic back key to its parent.
"""

import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageEnhance

from hexclack import render, tiles
from hexclack.actions import Runner
from hexclack.config import BACK_SLOT, COLS, HOME_SCREEN, ROWS, Action, Config, Key, KeyTile
from hexclack.device import Command, Draw
from hexclack.gestures import Gestures
from hexclack.music.bot import page_category_items, page_items, playlist_label, playlist_rows
from hexclack.music.browse import PlaylistRef

log = logging.getLogger(__name__)

FLASH_S = 1.0  # how long an error tint stays (docs/music.md section 3)
BUSY_HOURGLASS_S = 1.0  # after this, a still-busy key gets an hourglass on the dimmed face
POLL_S = 0.02  # gesture timer resolution
EPHEMERAL_SCREEN = "__ephemeral__"  # runtime-only; never a config screen name
EPHEMERAL_NEXT = "2,1"  # Next chrome when a page has more items
# Playlist slots after Home when Next may occupy EPHEMERAL_NEXT (Mini: 4).
PLAYLIST_LIST_CAPACITY = COLS * ROWS - 2
# Category browse: Any only on page 0 (with Home). Later pages match playlist-list capacity.
CATEGORY_ANY_SLOT = "1,0"
CATEGORY_FIRST_CAPACITY = COLS * ROWS - 3  # Home + Any + maybe Next
CATEGORY_LATER_CAPACITY = COLS * ROWS - 2  # Home + maybe Next


def slot_of(index: int) -> str:
    return f"{index % COLS},{index // COLS}"


def index_of(slot: str) -> int:
    col, row = (int(p) for p in slot.split(","))
    return row * COLS + col


def dimmed(image: Image.Image) -> Image.Image:
    return ImageEnhance.Brightness(image).enhance(0.5)


def tinted(image: Image.Image) -> Image.Image:
    return Image.blend(image, Image.new("RGB", image.size, (200, 0, 0)), 0.55)


def busy_wait_image(image: Image.Image) -> Image.Image:
    """Dimmed key with a centred mono hourglass while a slow action is still running."""
    base = dimmed(image).convert("RGBA")
    mark = tiles.hourglass_mark(max(1, image.size[0] // 2))
    base.alpha_composite(mark, ((base.width - mark.width) // 2, (base.height - mark.height) // 2))
    return base.convert("RGB")


@dataclass(frozen=True)
class PlaylistEntry:
    name: str
    icon: str | None = None
    tile: KeyTile | None = None


def _tile_from_payload(raw: object) -> KeyTile | None:
    if not isinstance(raw, dict):
        return None
    glyph, start, end = raw.get("glyph"), raw.get("start"), raw.get("end")
    if isinstance(glyph, str) and glyph and isinstance(start, str) and isinstance(end, str):
        return KeyTile(glyph=glyph, start=start, end=end)
    return None


def _playlist_entries_from_payload(payload: dict[str, object]) -> list[PlaylistEntry]:
    """Parse playlist_list.entries."""
    raw = payload.get("entries")
    if not isinstance(raw, list):
        return []
    out: list[PlaylistEntry] = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name:
                icon = item.get("icon")
                out.append(
                    PlaylistEntry(
                        name=name,
                        icon=icon if isinstance(icon, str) and icon else None,
                        tile=_tile_from_payload(item.get("tile")),
                    )
                )
        elif isinstance(item, str) and item:
            out.append(PlaylistEntry(name=item))
    return out


@dataclass
class PlaylistListSession:
    label: str
    entries: tuple[PlaylistEntry, ...]
    dated: bool = False
    colors: dict[str, tuple[int, int, int]] = field(default_factory=dict)  # shuffled tints for this open
    page: int = 0

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(e.name for e in self.entries)


@dataclass
class CategoryListSession:
    """Curated/Mine folder page. Picks are fixed when the page opens (titles show playlist names)."""

    label: str
    groups: dict[str, tuple[PlaylistRef, ...]]
    categories: tuple[str, ...]
    picks: dict[str, PlaylistRef]  # category -> playlist chosen for this open
    any_pick: PlaylistRef  # playlist for the Any key
    colors: dict[str, tuple[int, int, int]]  # shuffled category tints for this open
    page: int = 0


def _playlist_refs_from_group(raw: object) -> list[PlaylistRef]:
    """Parse category_list.groups values: {name, folder} dicts (or legacy bare names)."""
    if not isinstance(raw, list):
        return []
    out: list[PlaylistRef] = []
    for item in raw:
        if isinstance(item, PlaylistRef):
            out.append(item)
        elif isinstance(item, dict):
            name = item.get("name")
            folder = item.get("folder", "")
            if isinstance(name, str) and name and isinstance(folder, str):
                out.append(PlaylistRef(folder=folder, name=name))
        elif isinstance(item, str) and item:
            out.append(PlaylistRef(folder="", name=item))
    return out


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
        self._busy_at: dict[tuple[str, int], float] = {}  # when the action started
        self._busy_hourglass: set[tuple[str, int]] = set()  # slots already showing ⏳

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
            return render.key_image(
                Key(slot=slot, title=state.label, icon=state.icon, tile=key.tile),
                self.base,
            )
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
            name = str(key.action.fields["name"])
            rows = playlist_rows(name)
            if rows is not None:
                extra, day, year = rows
                bg = self.playlist_list.colors.get(name, tiles.PICK_FALLBACK_BG)
                return tiles.cached(
                    {
                        "kind": "playlist_rows",
                        "extra": extra,
                        "day": day,
                        "year": year,
                        "bg": list(bg),
                    },
                    render.KEY_SIZE,
                    lambda: tiles.playlist_tile(extra, day, year, bg=bg),
                )
        if self.category_list is not None and key.action is not None and key.action.fields.get("action") == "playlist":
            name = str(key.action.fields["name"])
            category = key.action.fields.get("category")
            if isinstance(category, str) and category:
                bg = self.category_list.colors.get(category, tiles.PICK_FALLBACK_BG)
                return tiles.cached(
                    {"kind": "pick_rows", "name": name, "category": category, "bg": list(bg)},
                    render.KEY_SIZE,
                    lambda n=name, c=category, b=bg: tiles.pick_tile(n, c, bg=b),
                )
        return render.key_image(key, self.base)

    def _playlist_list_keys(self) -> dict[str, Key]:
        assert self.playlist_list is not None
        entries = list(self.playlist_list.entries)
        items, has_next = page_items(entries, self.playlist_list.page, PLAYLIST_LIST_CAPACITY)
        keys: dict[str, Key] = {
            BACK_SLOT: Key(slot=BACK_SLOT, action=Action(kind="nav", fields={"home": True})),
        }
        playlist_slots = [slot_of(i) for i in range(1, COLS * ROWS) if not (has_next and slot_of(i) == EPHEMERAL_NEXT)]
        dated = self.playlist_list.dated
        for slot, entry in zip(playlist_slots, items, strict=False):
            # Icon-only when artwork is supplied (often already labeled); tile/title otherwise.
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
                tile=entry.tile,
                action=Action(kind="music", fields={"action": "playlist", "name": entry.name}),
            )
        if has_next:
            keys[EPHEMERAL_NEXT] = Key(
                slot=EPHEMERAL_NEXT,
                title="Next",
                action=Action(kind="nav", fields={"ephemeral_next": True}),
            )
        return keys

    def _category_list_keys(self) -> dict[str, Key]:
        assert self.category_list is not None
        page = self.category_list.page
        categories = list(self.category_list.categories)
        items, has_next = page_category_items(
            categories,
            page,
            first_capacity=CATEGORY_FIRST_CAPACITY,
            later_capacity=CATEGORY_LATER_CAPACITY,
        )
        keys: dict[str, Key] = {
            BACK_SLOT: Key(slot=BACK_SLOT, action=Action(kind="nav", fields={"home": True})),
        }
        if page == 0:
            any_pick = self.category_list.any_pick
            keys[CATEGORY_ANY_SLOT] = Key(
                slot=CATEGORY_ANY_SLOT,
                action=Action(
                    kind="music",
                    fields={
                        "action": "playlist",
                        "name": any_pick.name,
                        "folder": any_pick.folder,
                        "category": "Any",
                    },
                ),
            )
            first_content = 2
        else:
            first_content = 1
        cat_slots = [
            slot_of(i) for i in range(first_content, COLS * ROWS) if not (has_next and slot_of(i) == EPHEMERAL_NEXT)
        ]
        for slot, category in zip(cat_slots, items, strict=False):
            pick = self.category_list.picks[category]
            keys[slot] = Key(
                slot=slot,
                action=Action(
                    kind="music",
                    fields={
                        "action": "playlist",
                        "name": pick.name,
                        "folder": pick.folder,
                        "category": category,
                    },
                ),
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
        colors = tiles.shuffled_colors([e.name for e in packed]) if dated else {}
        self._clear_ephemeral()
        self.playlist_list = PlaylistListSession(label=label, entries=tuple(packed), dated=dated, colors=colors, page=0)
        self._clear_ephemeral_images()
        self.go(EPHEMERAL_SCREEN)

    def open_category_list(
        self,
        label: str,
        groups: dict[str, list[PlaylistRef]],
        order: list[str],
    ) -> None:
        """Show explore/saved picks. Each key gets one random playlist (name+folder) for this open."""
        if not order:
            return
        packed = {cat: tuple(refs) for cat in order if (refs := groups.get(cat))}
        if not packed:
            return
        picks = {cat: random.choice(refs) for cat, refs in packed.items()}
        pool = [ref for refs in packed.values() for ref in refs]
        any_pick = random.choice(pool)
        colors = tiles.shuffled_colors(["Any", *packed])
        self._clear_ephemeral()
        self.category_list = CategoryListSession(
            label=label,
            groups=packed,
            categories=tuple(packed),
            picks=picks,
            any_pick=any_pick,
            colors=colors,
            page=0,
        )
        self._clear_ephemeral_images()
        self.go(EPHEMERAL_SCREEN)

    def ephemeral_next_page(self) -> None:
        if self.playlist_list is not None:
            _items, has_next = page_items(
                list(self.playlist_list.names), self.playlist_list.page, PLAYLIST_LIST_CAPACITY
            )
            if not has_next:
                return
            self.playlist_list.page += 1
        elif self.category_list is not None:
            _items, has_next = page_category_items(
                list(self.category_list.categories),
                self.category_list.page,
                first_capacity=CATEGORY_FIRST_CAPACITY,
                later_capacity=CATEGORY_LATER_CAPACITY,
            )
            if not has_next:
                return
            self.category_list.page += 1
        else:
            return
        self._clear_ephemeral_images()
        self.gestures.reset()
        self.draw_screen()

    def handle_music_changed(self, screen: str, _index: int, changed: dict[str, object]) -> None:
        """Open ephemeral lists from music action payloads; ignore other keys.

        Ignores a payload whose originating screen is no longer visible (the user
        left while a slow Music action was still running), matching `_done`.
        """
        if screen != self.screen or self.asleep:
            return
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
        category_payload = changed.get("category_list")
        if isinstance(category_payload, dict):
            label = category_payload.get("label")
            groups_raw = category_payload.get("groups")
            order = category_payload.get("order")
            if isinstance(label, str) and isinstance(groups_raw, dict) and isinstance(order, list):
                groups = {str(k): refs for k, v in groups_raw.items() if (refs := _playlist_refs_from_group(v))}
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
        if fields.get("ephemeral_next"):
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
            self._poll_busy_hourglass()

    def _clear_busy_wait(self, slot: tuple[str, int]) -> None:
        self._busy_at.pop(slot, None)
        self._busy_hourglass.discard(slot)

    def _poll_busy_hourglass(self) -> None:
        """If a key has been busy for BUSY_HOURGLASS_S, overlay ⏳ on the dimmed face (once)."""
        now = self.clock()
        for slot, started in list(self._busy_at.items()):
            screen, index = slot
            if not self.runner.busy(screen, index):
                self._clear_busy_wait(slot)
                continue
            if slot in self._busy_hourglass or screen != self.screen or self.asleep:
                continue
            if now - started < BUSY_HOURGLASS_S:
                continue
            self._busy_hourglass.add(slot)
            self.submit(Draw(index, busy_wait_image(self.image(screen, slot_of(index)))))

    def _fire(self, index: int, key: Key | None, gesture: str) -> None:
        if key is None:
            return
        action: Action | None = key.gestures.get(gesture) if key.gestures else key.action
        log.info("%s %s %s", self.screen, slot_of(index), gesture)
        if action is not None and action.kind == "nav":
            self.nav(action.fields)
            return
        if (action is not None or key.toggle) and self.runner.submit(self.screen, index, key, action):
            self._busy_at[(self.screen, index)] = self.clock()
            self._busy_hourglass.discard((self.screen, index))

    def _done(self, screen: str, index: int, ok: bool) -> None:
        """From a worker: restore the key, or flash it red for FLASH_S on failure."""
        with self._lock:
            self._clear_busy_wait((screen, index))
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
