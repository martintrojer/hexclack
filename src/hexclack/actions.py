"""Run key actions off the device thread (docs/design.md sections 3 and 5).

Every action runs on a small worker pool, so a slow osascript (~0.8 s) or a hung HTTP call never
blocks the device owner. A second press of a key whose action is still running is dropped. A
toggle advances to its next state only after the shown state's action succeeded, so the label
never claims an action ran when it failed. `nav` changes the screen and is handled by the caller.
"""

import logging
import subprocess
import threading
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from hexclack.config import Action, Key
from hexclack.music import actions as music_actions
from hexclack.music.errors import MusicError
from hexclack.pihole import PiholeClient, PiholeError

log = logging.getLogger(__name__)

HTTP_TIMEOUT_S = 5
SHELL_TIMEOUT_S = 30
WORKERS = 4


class ActionError(Exception):
    pass


def run_action(action: Action, pihole: Callable[[str], PiholeClient]) -> dict[str, object] | None:
    """Run one non-nav action synchronously. Raises ActionError. Returns what a music action
    changed (see music.actions.run), else None."""
    f = action.fields
    try:
        match action.kind:
            case "shell":
                result = subprocess.run(
                    str(f["cmd"]), shell=True, capture_output=True, text=True, timeout=SHELL_TIMEOUT_S, check=False
                )
                if result.returncode != 0:
                    raise ActionError(f"shell exited {result.returncode}: {result.stderr.strip()[:200]}")
            case "applescript":
                result = subprocess.run(
                    ["/usr/bin/osascript", "-e", str(f["script"])],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if result.returncode != 0:
                    raise ActionError(f"osascript: {result.stderr.strip()[:200]}")
            case "http":
                request = urllib.request.Request(str(f["url"]), method=str(f["method"]))
                with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as reply:
                    reply.read()
            case "music":
                return music_actions.run(f)
            case "pihole":
                pihole(str(f["host"])).disable(int(f["disable_seconds"]))
            case other:
                raise ActionError(f"{other} is not a runnable action")
    except (MusicError, PiholeError, OSError, subprocess.TimeoutExpired) as err:
        raise ActionError(f"{action.kind}: {err}") from err
    return None


class Runner:
    """Dispatch key actions to workers, one in flight per key."""

    def __init__(
        self,
        pihole: Callable[[str], PiholeClient],
        on_done: Callable[[str, int, bool], None] = lambda _screen, _key, _ok: None,
        execute: Callable[[Action], dict[str, object] | None] | None = None,
        on_changed: Callable[[str, int, dict[str, object]], None] = lambda _screen, _key, _changed: None,
    ) -> None:
        self.pihole = pihole
        self.on_done = on_done  # feedback: (screen, key index, succeeded)
        self.execute = execute or (lambda action: run_action(action, self.pihole))
        self.on_changed = on_changed  # (screen, key, what the action changed): live keys show it at once
        self.pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="action")
        self._busy: set[tuple[str, int]] = set()
        self._lock = threading.Lock()
        self.toggle_index: dict[tuple[str, int], int] = {}
        # Status-backed toggles: the state index last read from the device (None: unknown/unreachable).
        self.known: dict[tuple[str, int], int | None] = {}

    def busy(self, screen: str, index: int) -> bool:
        with self._lock:
            return (screen, index) in self._busy

    def toggle_state(self, screen: str, index: int, key: Key) -> int:
        """The state the key shows: for a status-backed toggle, the polled state (0 until first read)."""
        if key.toggle_status is not None:
            return self.known.get((screen, index)) or 0
        return self.toggle_index.get((screen, index), key.toggle_initial)

    def set_known(self, screen: str, index: int, state: int | None) -> None:
        self.known[(screen, index)] = state

    def submit(self, screen: str, index: int, key: Key, action: Action | None) -> bool:
        """Start the action for a press. Returns False if dropped (that key is still busy)."""
        if key.toggle and key.toggle_status is not None:
            known = self.known.get((screen, index))
            if known is None:
                log.warning("%s key %d: state unknown (status unreachable); press ignored", screen, index)
                return False
            action = key.toggle[(known + 1) % len(key.toggle)].action  # move to the next real state
        elif key.toggle:
            action = key.toggle[self.toggle_state(screen, index, key)].action
        if action is None:
            return False
        slot = (screen, index)
        with self._lock:
            if slot in self._busy:
                log.info("press on %s key %d dropped: still running", screen, index)
                return False
            self._busy.add(slot)
        self.pool.submit(self._run, screen, index, key, action)
        return True

    def _run(self, screen: str, index: int, key: Key, action: Action) -> None:
        ok = True
        try:
            changed = self.execute(action)
            if changed:
                self.on_changed(screen, index, changed)
        except ActionError as err:
            ok = False
            log.error("%s key %d: %s", screen, index, err)
        except Exception:
            ok = False
            log.exception("%s key %d: unexpected error", screen, index)
        if ok and key.toggle and key.toggle_status is None:  # status-backed: the re-poll decides (toggle_index unused)
            current = self.toggle_state(screen, index, key)
            self.toggle_index[(screen, index)] = (current + 1) % len(key.toggle)
        with self._lock:
            self._busy.discard((screen, index))
        self.on_done(screen, index, ok)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
