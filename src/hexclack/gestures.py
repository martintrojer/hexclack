"""Tap, double and hold on one key (the Key Logic replacement, docs/design.md section 5).

Pure timing logic. The caller feeds key down/up events and calls `poll()` regularly; both return
the gestures that fired. Time is passed in, so tests drive it without sleeping.

Rules:
- A key with only `tap` fires on release, at once.
- A key with `double` fires `tap` only after `double_ms` with no second press; a second press
  inside that window fires `double` (on its release) and no `tap`.
- A key with `hold` fires `hold` once the key has been down for `hold_ms`, still down; that press
  then fires nothing on release.
"""

from dataclasses import dataclass, field

Gesture = str  # "tap" | "double" | "hold"


@dataclass
class _KeyState:
    down_at: float | None = None
    held: bool = False
    pending_tap_at: float | None = None  # release time of a first tap waiting for a possible double
    second_press: bool = False


@dataclass
class Gestures:
    double_ms: int = 300
    hold_ms: int = 500
    _keys: dict[int, _KeyState] = field(default_factory=dict)

    def event(self, key: int, pressed: bool, now: float, has: set[Gesture]) -> list[Gesture]:
        """A key went down (pressed=True) or up. `has` is the set of gestures the key defines."""
        s = self._keys.setdefault(key, _KeyState())
        fired: list[Gesture] = []
        if pressed:
            if s.pending_tap_at is not None and "double" in has:
                s.second_press = True
                s.pending_tap_at = None
            s.down_at = now
            s.held = False
            return fired
        if s.down_at is None:  # an up without a down (e.g. pressed before startup): ignore
            return fired
        if s.held:
            pass  # hold already fired; the release does nothing
        elif "hold" in has and (now - s.down_at) * 1000 >= self.hold_ms:
            fired.append("hold")  # released exactly at the threshold, before poll() saw it
        elif s.second_press:
            fired.append("double")
        elif "double" in has:
            s.pending_tap_at = now
        else:
            fired.append("tap")
        s.down_at = None
        s.held = False
        s.second_press = False
        return fired

    def poll(self, now: float, keys: dict[int, set[Gesture]]) -> list[tuple[int, Gesture]]:
        """Fire the timer-driven gestures: holds that crossed hold_ms, taps whose double window closed."""
        fired: list[tuple[int, Gesture]] = []
        for key, s in self._keys.items():
            has = keys.get(key, set())
            if s.down_at is not None and not s.held and "hold" in has and (now - s.down_at) * 1000 >= self.hold_ms:
                s.held = True
                s.second_press = False
                fired.append((key, "hold"))
            if s.pending_tap_at is not None and (now - s.pending_tap_at) * 1000 >= self.double_ms:
                s.pending_tap_at = None
                fired.append((key, "tap"))
        return fired

    def reset(self) -> None:
        """Forget all in-flight presses (screen change, device reopen)."""
        self._keys.clear()
