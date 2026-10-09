"""What the deck shows and what a press does: screens, navigation, gestures and key feedback.

Pure with respect to the device: it turns key events into Draw commands (via `submit`) and action
runs (via the Runner). Navigation follows docs/design.md section 5: pages form a line (prev/next,
no wrap), a folder's 0,0 is the automatic back key to its parent.
"""

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageEnhance

from hexclack import render
from hexclack.actions import Runner
from hexclack.config import BACK_SLOT, COLS, HOME_SCREEN, ROWS, Action, Config, Key
from hexclack.device import Command, Draw
from hexclack.gestures import Gestures

log = logging.getLogger(__name__)

FLASH_S = 1.0  # how long an error tint stays (docs/music.md section 3)
POLL_S = 0.02  # gesture timer resolution


def slot_of(index: int) -> str:
    return f"{index % COLS},{index // COLS}"


def index_of(slot: str) -> int:
    col, row = (int(p) for p in slot.split(","))
    return row * COLS + col


def dimmed(image: Image.Image) -> Image.Image:
    return ImageEnhance.Brightness(image).enhance(0.5)


def tinted(image: Image.Image) -> Image.Image:
    return Image.blend(image, Image.new("RGB", image.size, (200, 0, 0)), 0.55)


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

    # -- drawing -----------------------------------------------------------------------------

    def image(self, screen: str, slot: str) -> Image.Image:
        """The current image of a slot, with the alert border on keys that ask for it."""
        image = self._base_image(screen, slot)
        key = self.cfg.screens[screen].keys.get(slot)
        if key is not None and key.alerts:
            return render.alert_border(image, self.alert_severity())
        return image

    def alerts_changed(self) -> None:
        """Redraw the visible keys that show the alert border."""
        if self.asleep:
            return
        for slot, key in self.cfg.screens[self.screen].keys.items():
            if key.alerts:
                self.submit(Draw(index_of(slot), self.image(self.screen, slot)))

    def _base_image(self, screen: str, slot: str) -> Image.Image:
        """Static images cached; a toggle shows its current state; a widget its latest image."""
        s = self.cfg.screens[screen]
        key = s.keys.get(slot)
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
            key = self.cfg.screens[screen].keys.get(slot_of(index))
            self.submit(Draw(index, render.alert_border(image, self.alert_severity()) if key and key.alerts else image))
        # If the key was busy, _done() redraws it from widget_image(), which already holds this image.

    def blank(self) -> None:
        black = Image.new("RGB", (render.KEY_SIZE, render.KEY_SIZE), "black")
        for i in range(ROWS * COLS):
            self.submit(Draw(i, black))

    # -- navigation --------------------------------------------------------------------------

    def go(self, screen: str) -> None:
        log.info("screen %s -> %s", self.screen, screen)
        self.screen = screen
        self.gestures.reset()
        self.draw_screen()

    def nav(self, fields: dict[str, object]) -> None:
        if fields.get("home"):
            self.go_home()
            return
        if "folder" in fields:
            self.go(str(fields["folder"]))
            return
        page = self.screen
        while self.cfg.screens[page].kind == "folder":  # nav from a folder acts on its page
            page = self.cfg.screens[page].parent or self.cfg.pages[0]
        i = self.cfg.pages.index(page)
        step = 1 if fields.get("page") == "next" else -1
        j = i + step
        if 0 <= j < len(self.cfg.pages):  # pages form a line: no wrap
            self.go(self.cfg.pages[j])

    def go_home(self) -> None:
        """One press from any screen, at any depth (user request: no step-by-step back)."""
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
            screen = self.cfg.screens[self.screen]
            if screen.kind == "folder" and slot == BACK_SLOT:
                if not pressed:
                    self.go_home()
                return
            key = screen.keys.get(slot)
            if pressed and key is not None and (key.action or key.gestures or key.toggle):
                self.submit(Draw(index, dimmed(self.image(self.screen, slot))))
            for gesture in self.gestures.event(index, pressed, self.clock(), self._gestures_of(key)):
                self._fire(index, key, gesture)
            if not pressed and key is not None and not self.runner.busy(self.screen, index):
                self.submit(Draw(index, self.image(self.screen, slot)))  # undim; a running action undims on done

    def poll(self) -> None:
        """From the tick thread every POLL_S: timer-driven gestures (hold, delayed tap)."""
        with self._lock:
            screen = self.cfg.screens[self.screen]
            has = {index_of(s): self._gestures_of(k) for s, k in screen.keys.items()}
            for index, gesture in self.gestures.poll(self.clock(), has):
                self._fire(index, screen.keys.get(slot_of(index)), gesture)

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
