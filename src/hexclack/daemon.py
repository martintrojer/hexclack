"""Wire the device owner, actions, widgets, idle state and watchdog together for `hexclack run`."""

import logging
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from hexclack import alerts, cocoa, render
from hexclack.actions import Runner
from hexclack.brightness import OVERRIDE_S, AutoBrightness, Curve, override_active, take_override
from hexclack.config import Config
from hexclack.deck import POLL_S, Deck
from hexclack.device import Brightness, Draw, Owner, Resume, StreamDeckIO, Suspend, Tick
from hexclack.idle import Idle, IdleTimer, brightness_for, quiet_hours
from hexclack.pihole import PiholeClient
from hexclack.watchdog import Watchdog
from hexclack.widgets import Dispatcher
from hexclack.widgets import health as health_widget
from hexclack.widgets import pihole as pihole_widget
from hexclack.widgets import sensors as sensors_widget
from hexclack.widgets import status as status_widget
from hexclack.widgets.now_playing import SAFETY_POLL_S, LoveWidget, MusicWatcher, NowPlayingWidget

log = logging.getLogger(__name__)

INTERVAL_S = 10
HANG_POLL_S = 1


def now() -> datetime:
    return datetime.now(UTC)


def notify(message: str) -> None:
    """A macOS notification. The text goes through argv, so it never needs quoting."""
    script = 'on run argv\n display notification (item 1 of argv) with title "hexclack"\nend run'
    subprocess.run(["/usr/bin/osascript", "-", message], input=script, text=True, check=False, timeout=10)


def hard_exit(code: int) -> None:
    """Exit now, from any thread. A hung hidapi call cannot be unwound, so skip cleanup."""
    logging.shutdown()
    os._exit(code)


def run(cfg: Config, base: Path) -> None:
    deck: Deck
    io = StreamDeckIO(on_key=lambda key, pressed: on_key(key, pressed))
    watchdog = Watchdog(io, now, hard_exit, notify, health_timeout_s=cfg.watchdog.health_timeout_s)
    idle = IdleTimer(cfg.device.clock_minutes, cfg.device.sleep_minutes, now())
    clients: dict[str, PiholeClient] = {}

    def pihole(host: str) -> PiholeClient:
        if host not in clients:
            clients[host] = PiholeClient(host, password=lambda: keychain(host))
        return clients[host]

    def keychain(host: str) -> str:
        from hexclack.pihole import keychain_password

        return keychain_password(host, cfg.pihole_service)

    def redraw() -> None:
        owner.submit(Brightness(brightness_for(idle.state, auto.current if auto else cfg.device.brightness)))
        if idle.state == Idle.AWAKE:  # after a reopen during the saver, the next clock minute redraws
            deck.draw_screen()
        elif idle.state == Idle.OFF:  # e.g. a reopen while off: stay dark
            deck.blank()

    def screen_off() -> None:
        deck.blank()
        owner.submit(Brightness(brightness_for(Idle.OFF, cfg.device.brightness)))

    owner = Owner(io, watchdog, now, on_healthy=redraw)
    widgets = Dispatcher(draw=lambda screen, index, image: deck.widget_drew(screen, index, image))
    deck = Deck(
        cfg,
        base,
        owner.submit,
        lambda done: Runner(pihole=pihole, on_done=done),
        widget_image=widgets.image,
        alert_severity=lambda: worst_alert(),
    )
    music, hosts = _place_widgets(cfg, widgets)
    statuses = _place_status_toggles(cfg, base, widgets, deck)
    healths = _place_health(cfg, widgets)
    auto = AutoBrightness(Curve(cfg.auto_brightness.points), cfg.device.brightness) if cfg.auto_brightness else None
    auto_url = cfg.auto_brightness.url if cfg.auto_brightness else None
    nonlocal_override = [0.0]  # monotonic time a tuning override runs until

    def follow_light() -> None:
        """Every 60 s: brightness from the room light. Missing, failed or stale -> the fixed value."""
        if auto is None or auto_url is None:
            return
        reading = sensors_widget.poll("_auto", "_brightness", auto_url).data["reading"]
        assert isinstance(reading, sensors_widget.Reading)
        ok = reading.error is None and not reading.stale and reading.light is not None
        new = auto.update(reading.light if ok else None)
        log.info(
            "light %s -> target %d",
            reading.light if ok else "unavailable",
            auto.curve.at(reading.light) if ok and reading.light is not None else cfg.device.brightness,
        )
        if new is not None and override_active(nonlocal_override[0]):
            return  # a tuning override is showing; the curve takes over when it runs out
        if new is not None:
            log.info("brightness %d (light %s)", new, reading.light if ok else "unavailable")
            if idle.state != Idle.OFF:
                owner.submit(Brightness(new))

    health_watch = [p.widget for p in widgets.placements if isinstance(p.widget, health_widget.HealthWidget)]
    sensor_watch = [p.widget for p in widgets.placements if isinstance(p.widget, sensors_widget.SensorsWidget)]

    def current_alerts() -> list[tuple[str, int]]:
        found = alerts.collect(
            {w.title: w.latest for w in health_watch if w.latest is not None},
            {w.title: w.latest for w in sensor_watch if w.latest is not None},
        )
        return [(a.label, int(a.severity)) for a in found]

    def worst_alert() -> int:
        found = current_alerts()
        return found[0][1] if found else 0  # collect() sorts worst first

    def poll_status(screen: str, slot: str) -> None:
        key = cfg.screens[screen].keys[slot]
        widgets.publish(status_widget.poll(screen, slot, key))

    from hexclack.music import bridge

    watcher = MusicWatcher(bridge.now_playing, widgets.publish, artwork=bridge.artwork)

    def after_action(screen: str, index: int, ok: bool) -> None:
        if music:
            watcher.notified()  # a press may have changed playback or Love: refresh the music keys
        slot = f"{index % 3},{index // 3}"
        if (screen, slot) in statuses:
            poll_status(screen, slot)  # read the real state back at once, not at the next 30 s poll

    deck.runner.on_done = _chain(deck.runner.on_done, after_action)

    def on_changed(screen: str, index: int, changed: dict[str, object]) -> None:
        deck.handle_music_changed(screen, index, changed)  # bot mode=list opens the ephemeral folder
        if music:
            # Favourite or Play/Pause: show its result now (Music reports favourites ~10 s late).
            watcher.pressed(changed)

    deck.runner.on_changed = on_changed

    def on_key(key: int, pressed: bool) -> None:
        was = idle.state
        if not idle.key(key, pressed, now()):
            if was != Idle.AWAKE:  # any key wakes; the waking press is a no-op
                log.info("idle: %s -> awake", was)
                deck.asleep = False
                redraw()
            return
        deck.on_key(key, pressed)

    owner.start()
    stop = threading.Event()

    def watch_hangs() -> None:
        while not stop.wait(HANG_POLL_S):
            watchdog.check_hang(owner.heartbeat)

    def gesture_timers() -> None:
        while not stop.wait(POLL_S):
            deck.poll()

    def poll_widgets() -> None:
        last_music = 0.0
        last_pihole = -float(pihole_widget.POLL_S)
        last_status = -float(status_widget.POLL_S)
        last_health = -float(health_widget.POLL_S)
        last_light = -float(sensors_widget.POLL_S)
        while True:
            t = now().timestamp()
            if music and t - last_music >= SAFETY_POLL_S:
                last_music = t
                guarded("music refresh", watcher.refresh_soon)  # on its own thread: Music may be wedged
            if hosts and t - last_pihole >= pihole_widget.POLL_S:
                last_pihole = t
                for host in hosts:
                    guarded(f"pihole {host}", lambda host=host: widgets.publish(pihole_widget.poll(pihole(host))))
            if statuses and t - last_status >= status_widget.POLL_S:
                last_status = t
                for screen, slot in statuses:
                    guarded(f"status {screen} {slot}", lambda s=screen, k=slot: poll_status(s, k))
            if auto and t - last_light >= sensors_widget.POLL_S:
                last_light = t
                guarded("auto brightness", follow_light)
            if healths and t - last_health >= health_widget.POLL_S:
                last_health = t
                for screen, slot, url in healths:
                    kind = cfg.screens[screen].keys[slot].widget
                    poller = sensors_widget.poll if kind == "sensors" else health_widget.poll
                    guarded(f"{kind} {url}", lambda s=screen, k=slot, u=url, p=poller: widgets.publish(p(s, k, u)))
            if stop.wait(1):
                return

    threading.Thread(target=watch_hangs, name="watchdog", daemon=True).start()
    threading.Thread(target=poll_widgets, name="widgets", daemon=True).start()
    threading.Thread(target=gesture_timers, name="gestures", daemon=True).start()
    cocoa.start(
        on_wake=lambda: owner.urgent(Resume()),
        on_sleep=lambda: owner.urgent(Suspend()),
        on_music=watcher.notified if music else lambda: None,
    )
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    log.info("hexclack running: %d screens, start on %s", len(cfg.screens), deck.screen)
    try:
        owner.submit(Tick())
        shown_minute = ""
        shown_alerts: list[tuple[str, int]] = []
        shown_art: bytes | None = None
        shown_severity = -1
        while not stop.wait(1):
            t = now()
            tuning = take_override()
            if tuning is not None:
                nonlocal_override[0] = time.monotonic() + OVERRIDE_S
                log.info("brightness %d (tuning, %d s)", tuning, OVERRIDE_S)
                if idle.state != Idle.OFF:
                    owner.submit(Brightness(tuning))
            if t.second % INTERVAL_S == 0:
                owner.submit(Tick())
            quiet = quiet_hours(t.astimezone(), cfg.device.quiet_start, cfg.device.quiet_end)
            changed = idle.tick(t, alerting=worst_alert() > 0 and not quiet)
            if changed is not None:
                log.info("idle: -> %s", changed)
                deck.asleep = True  # widgets stop drawing over the saver
                shown_minute = ""
                if changed == Idle.CLOCK:  # from awake, or back from off when an alert appears
                    owner.submit(Brightness(auto.current if auto else cfg.device.brightness))
            if idle.state == Idle.AWAKE:
                severity = worst_alert()
                if severity != shown_severity:  # an alert came or went: recolour the border keys
                    shown_severity = severity
                    deck.alerts_changed()
            else:
                shown_severity = -1  # waking redraws the screen; re-check after
            if idle.state == Idle.CLOCK:
                local = t.astimezone()
                minute = local.strftime("%H:%M")
                now_alerts = current_alerts()
                art = watcher.playing_art() if music else None  # album art behind the digits while playing
                # Redraw once a minute (the colour steps with it), or at once when the alerts or art change.
                if minute != shown_minute or now_alerts != shown_alerts or art is not shown_art:
                    shown_minute, shown_alerts, shown_art = minute, now_alerts, art
                    colour = render.clock_colour(local.hour * 60 + local.minute)
                    keys = render.clock_keys(minute, colour=colour, alerts=now_alerts, background=art)
                    for index, image in keys.items():
                        owner.submit(Draw(index, image))
            elif changed == Idle.OFF:
                screen_off()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        deck.runner.shutdown()
        owner.stop()
        owner.thread.join(timeout=3)


def _chain(
    first: Callable[[str, int, bool], None], second: Callable[[str, int, bool], None]
) -> Callable[[str, int, bool], None]:
    def both(screen: str, index: int, ok: bool) -> None:
        first(screen, index, ok)
        second(screen, index, ok)

    return both


def _place_widgets(cfg: Config, widgets: Dispatcher) -> tuple[bool, list[str]]:
    """Create one widget per widget key. Returns (any music widget, Pi-hole hosts to poll)."""
    from hexclack.deck import index_of

    music = False
    hosts: list[str] = []
    for name, screen in cfg.screens.items():
        for slot, key in screen.keys.items():
            if key.widget == "now-playing":
                widgets.add(name, index_of(slot), NowPlayingWidget())
                music = True
            elif key.widget == "now-playing-love":
                widgets.add(name, index_of(slot), LoveWidget())
                music = True
            elif key.widget == "pihole-status":
                host = str(key.action.fields["host"]) if key.action and key.action.kind == "pihole" else None
                if host is None:
                    log.warning("%s %s: pihole-status widget needs a pihole action for its host", name, slot)
                    continue
                widgets.add(name, index_of(slot), pihole_widget.PiholeWidget(host, key.title or host))
                hosts.append(host)
    return music, hosts


def _place_status_toggles(cfg: Config, base: Path, widgets: Dispatcher, deck: Deck) -> list[tuple[str, str]]:
    """A widget for each status-backed toggle; it keeps the Runner's known state in sync."""
    from hexclack.deck import index_of

    placed: list[tuple[str, str]] = []
    for name, screen in cfg.screens.items():
        for slot, key in screen.keys.items():
            if key.toggle_status is None:
                continue
            index = index_of(slot)

            def on_state(state: int | None, name: str = name, index: int = index) -> None:
                deck.runner.set_known(name, index, state)

            widgets.add(name, index, status_widget.StatusToggleWidget(name, slot, key, base, on_state))
            placed.append((name, slot))
    return placed


def guarded(what: str, fn: Callable[[], object]) -> None:
    """Run one poll; an unexpected exception is logged and the loop keeps going (infodisp 0bd43a6:
    one bad tick, e.g. http.client.IncompleteRead, must not stop every later poll)."""
    try:
        fn()
    except Exception:
        log.exception("%s failed", what)


def _place_health(cfg: Config, widgets: Dispatcher) -> list[tuple[str, str, str]]:
    """A HealthWidget for each health-json key. Returns (screen, slot, url) to poll."""
    from hexclack.deck import index_of

    placed: list[tuple[str, str, str]] = []
    for name, screen in cfg.screens.items():
        for slot, key in screen.keys.items():
            if key.widget == "health-json" and key.health_url:
                widgets.add(name, index_of(slot), health_widget.HealthWidget(name, slot, key.title or "health"))
                placed.append((name, slot, key.health_url))
            elif key.widget == "sensors" and key.health_url:
                widgets.add(name, index_of(slot), sensors_widget.SensorsWidget(name, slot, key.title or "room"))
                placed.append((name, slot, key.health_url))
    return placed
