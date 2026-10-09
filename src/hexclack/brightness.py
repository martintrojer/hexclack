"""Deck brightness from the room light (user request; sensor's LTR303, via infodisp's /sensors).

`visible_light` is a raw sensor count (visible+IR minus IR at gain 48), not lux, so the curve is
tuned on the deck, not derived. Brightness follows a piecewise-linear curve between the configured
points, changes only when the target moves by HYSTERESIS or more (no flicker on small changes),
and falls back to the fixed configured brightness when the reading is missing, failed or stale.
"""

import time
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

HYSTERESIS = 8  # percentage points: clear steps, no flicker (tuned on the deck)
# `hexclack brightness N` writes N here; the daemon applies it and holds it for OVERRIDE_S (tuning).
OVERRIDE_FILE = Path.home() / "Library/Application Support/hexclack/brightness-override"
OVERRIDE_S = 300


def take_override(path: Path = OVERRIDE_FILE) -> int | None:
    """A pending tuning override, consumed (the file is removed). None if there is none."""
    try:
        value = int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    path.unlink(missing_ok=True)
    return max(0, min(100, value))


def override_active(until: float) -> bool:
    return time.monotonic() < until


@dataclass(frozen=True)
class Curve:
    points: tuple[tuple[float, int], ...]  # (light, percent), sorted by light

    def at(self, light: float) -> int:
        pts = self.points
        if light <= pts[0][0]:
            return pts[0][1]
        for (x0, y0), (x1, y1) in pairwise(pts):
            if light <= x1:
                return round(y0 + (y1 - y0) * (light - x0) / (x1 - x0))
        return pts[-1][1]


class AutoBrightness:
    def __init__(self, curve: Curve, fallback: int) -> None:
        self.curve = curve
        self.fallback = fallback
        self.current = fallback

    def update(self, light: float | None) -> int | None:
        """A new reading (None: missing, failed or stale). Returns the new brightness if it should
        change, else None."""
        target = self.fallback if light is None else self.curve.at(light)
        if abs(target - self.current) < HYSTERESIS and not (light is None and target != self.current):
            return None
        self.current = target
        return target
