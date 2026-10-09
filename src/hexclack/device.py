"""The device owner: the only daemon thread that calls hidapi (docs/design.md section 3).

`StreamDeckIO` adapts the streamdeck library to the watchdog's DeviceIO protocol. `Owner` runs one
thread that drains a bounded command queue. Around every device call it records a heartbeat (the
start time of the call in flight), which a separate watchdog thread reads to detect a hung call.
"""

import contextlib
import logging
import queue
import re
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from PIL import Image

from hexclack import render
from hexclack.watchdog import State, Watchdog

if TYPE_CHECKING:
    from StreamDeck.Devices.StreamDeck import StreamDeck

log = logging.getLogger(__name__)

MINI_PID = 0x90  # Stream Deck Mini MK2 (R1)
QUEUE_SIZE = 64

KeyCallback = Callable[[int, bool], None]


def usb_serials(product: str = "Stream Deck Mini") -> list[str]:
    """Serials of attached Minis from the IORegistry. Opens nothing and never touches hidapi, so it is
    safe to call while the device is wedged: this is how a replug is noticed."""
    out = subprocess.run(
        ["/usr/sbin/ioreg", "-p", "IOUSB", "-l", "-w0", "-r", "-n", product],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    ).stdout
    return re.findall(r'"USB Serial Number" = "([^"]+)"', out)


class StreamDeckIO:
    """DeviceIO over the streamdeck library. Every method may raise OSError (TransportError is one)."""

    def __init__(self, on_key: KeyCallback | None = None) -> None:
        self.deck: StreamDeck | None = None
        self.on_key = on_key

    def _find(self) -> "list[StreamDeck]":
        from StreamDeck.DeviceManager import DeviceManager  # loads hidapi; imported only when needed

        return [d for d in DeviceManager().enumerate() if d.product_id() == MINI_PID]

    def enumerate_serials(self) -> list[str]:
        return usb_serials()

    def open(self) -> str:
        found = self._find()
        if not found:
            raise OSError("no Stream Deck Mini found")
        deck = found[0]
        deck.open()
        if self.on_key is not None:
            callback = self.on_key
            deck.set_key_callback(lambda _deck, key, pressed: callback(key, pressed))
        self.deck = deck
        return deck.get_serial_number()

    def close(self) -> None:
        deck, self.deck = self.deck, None
        if deck is not None:
            # close() leaves the library read thread running; stop it so a reopen does not leave a stale reader.
            with contextlib.suppress(Exception):
                deck.set_key_callback(None)
                deck.run_read_thread = False
            with contextlib.suppress(Exception):
                deck.close()

    def reset(self) -> None:
        self._deck().reset()

    def is_open(self) -> bool:
        return self.deck is not None and self.deck.is_open() and self.deck.connected()

    def reader_alive(self) -> bool:
        thread = getattr(self.deck, "read_thread", None)
        return thread is not None and thread.is_alive()

    def firmware_version(self) -> str:
        return self._deck().get_firmware_version()

    def set_brightness(self, percent: int) -> None:
        self._deck().set_brightness(percent)

    def set_key_image(self, key: int, image: Image.Image) -> None:
        deck = self._deck()
        deck.set_key_image(key, render.to_device(deck, image))

    def _deck(self) -> "StreamDeck":
        if self.deck is None:
            raise OSError("device not open")
        return self.deck


@dataclass(frozen=True)
class Draw:
    key: int
    image: Image.Image


@dataclass(frozen=True)
class Brightness:
    percent: int


@dataclass(frozen=True)
class Tick:
    """Run one watchdog step (health check, reopen, ...). Sent every interval and on wake."""


@dataclass(frozen=True)
class Suspend:
    """The Mac is about to sleep: close the device now so the sleep ack is not held up."""


@dataclass(frozen=True)
class Resume:
    """The Mac woke: reopen on this tick."""


Command = Draw | Brightness | Tick | Suspend | Resume


class Owner:
    """Owns the device. Only this thread calls into StreamDeckIO."""

    def __init__(
        self,
        io: StreamDeckIO,
        watchdog: Watchdog,
        clock: Callable[[], datetime],
        on_healthy: Callable[[], None] = lambda: None,
    ) -> None:
        self.io = io
        self.watchdog = watchdog
        self.clock = clock
        self.on_healthy = on_healthy  # e.g. redraw the screen after a (re)open
        self.commands: queue.Queue[Command] = queue.Queue(maxsize=QUEUE_SIZE)
        self.heartbeat: datetime | None = None  # start of the device call in flight, else None
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="device-owner", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.commands.put(Tick())

    def submit(self, command: Command) -> None:
        """Enqueue from any thread. A full queue drops the oldest draw, never a Tick."""
        if isinstance(command, Draw) and not self.watchdog.accepting_draws:
            return
        while True:
            try:
                self.commands.put_nowait(command)
                return
            except queue.Full:
                self._drop_oldest_draw()

    def urgent(self, command: Command) -> None:
        """Put command at the head of the queue (sleep cannot wait behind queued draws)."""
        with self.commands.mutex:
            self.commands.queue.appendleft(command)
            self.commands.unfinished_tasks += 1
            self.commands.not_empty.notify()

    def _drop_oldest_draw(self) -> None:
        with self.commands.mutex:
            for i, queued in enumerate(self.commands.queue):
                if isinstance(queued, Draw):
                    del self.commands.queue[i]
                    self.commands.not_full.notify()
                    return
        # Only Ticks queued: one more Tick is redundant, so drop the new one by draining one.
        with contextlib.suppress(queue.Empty):
            self.commands.get_nowait()

    def _call[T](self, fn: Callable[[], T]) -> T:
        self.heartbeat = self.clock()
        try:
            return fn()
        finally:
            self.heartbeat = None

    def _run(self) -> None:
        while not self._stop.is_set():
            command = self.commands.get()
            if self._stop.is_set():
                break
            try:
                self._handle(command)
            except OSError as err:
                log.warning("device error: %s", err)
                self.watchdog.on_transport_error()
        self._call(self.io.close)

    def _handle(self, command: Command) -> None:
        match command:
            case Tick():
                before = self.watchdog.state
                self._call(self.watchdog.tick)
                if self.watchdog.state == State.HEALTHY and before != State.HEALTHY:
                    self.on_healthy()
            case Draw(key, image):
                if self.watchdog.state in (State.HEALTHY, State.SUSPECT):
                    self._call(lambda: self.io.set_key_image(key, image))
            case Suspend():
                self._call(self.io.close)
                self.watchdog.suspend()
            case Resume():
                self.watchdog.resume()
                self._handle(Tick())
            case Brightness(percent):
                if self.watchdog.state in (State.HEALTHY, State.SUSPECT):
                    self._call(lambda: self.io.set_brightness(percent))
