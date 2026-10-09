"""ScriptingBridge reads of Music for the live keys (docs/music.md sections 3 and 5).

The only music module that touches pyobjc (no stubs; ty ignores pyobjc attributes here). Lessons
from a separate sensor service, which spent many commits being a good Music citizen:

- Never launch Music by reading it. Bind to the running process by PID: an event to a PID that
  has quit fails, where a bundle-ID reference would relaunch Music (infodisp df2bc8d, 1b0d05f).
- Bound every Apple Event: a Music stuck on a modal dialog otherwise blocks for ~2 min per read.
  `setTimeout_` is in ticks (1/60 s) (infodisp 0bd43a6).
- Read one coherent track: resolve `currentTrack` once (`.get()`); the lazy reference would
  re-resolve per property, and a skip mid-read mixes two tracks (infodisp 1c6f3b1).
- Each optional property has its own try: one failing property must not throw away the rest
  (infodisp 1524030).
- Run in an autorelease pool: these calls happen on long-lived threads with no Cocoa run loop to
  drain autoreleased objects (infodisp 1b0d05f).

Callers get plain values. Nothing here raises: a gone or wedged Music reads as stopped.
"""

from collections.abc import Callable
from dataclasses import dataclass

import objc

BUNDLE_ID = "com.apple.Music"
EVENT_TIMEOUT_TICKS = 120  # 2 s

# Music's player state four-char codes (Music.sdef ePlS).
_STATES = {b"kPSP": "playing", b"kPSp": "paused", b"kPSS": "stopped", b"kPSF": "playing", b"kPSR": "playing"}


@dataclass(frozen=True)
class NowPlaying:
    state: str  # "playing" | "paused" | "stopped"
    track_id: str | None = None  # persistent ID: the artwork cache key
    title: str | None = None
    artist: str | None = None
    favorited: bool = False


def _music():  # noqa: ANN202 - an untyped pyobjc proxy, or None when Music is not running
    """A Music proxy bound to the running process, or None. Never launches Music."""
    import AppKit
    import ScriptingBridge

    running = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID)
    if not running or running[0].isTerminated():
        return None
    app = ScriptingBridge.SBApplication.applicationWithProcessIdentifier_(running[0].processIdentifier())
    if app is None:
        return None
    app.setTimeout_(EVENT_TIMEOUT_TICKS)
    return app


def _try[T](read: Callable[[], T], default: T) -> T:
    try:
        return read()
    except Exception:  # an optional property Music cannot answer for this track (e.g. a station)
        return default


def now_playing() -> NowPlaying:
    """State and the current track, read as one snapshot."""
    with objc.autorelease_pool():
        try:
            app = _music()
            if app is None:
                return NowPlaying("stopped")
            state = _STATES.get(int(app.playerState()).to_bytes(4, "big"), "stopped")
            if state == "stopped":
                return NowPlaying("stopped")
            track = app.currentTrack().get()  # resolve once: every property comes from this track
        except Exception:  # Apple Events fail in many ways (Music quitting, a modal dialog, a timeout)
            return NowPlaying("stopped")
        if track is None:
            return NowPlaying(state)
        return NowPlaying(
            state=state,
            track_id=_try(lambda: str(track.persistentID() or "") or None, None),
            title=_try(track.name, None),
            artist=_try(track.artist, None),
            favorited=_try(lambda: bool(track.favorited()), False),
        )


def artwork(track_id: str | None = None) -> bytes | None:
    """The current track's artwork as encoded bytes (JPEG or PNG), or None.

    With `track_id`, returns None unless the current track still has that persistent ID, so a skip
    between the state read and this fetch cannot cache one track's art under another (spike s10:
    rawData() is an SBObject; .get().data() holds the bytes).
    """
    with objc.autorelease_pool():
        try:
            app = _music()
            if app is None:
                return None
            track = app.currentTrack().get()
            if track is None or (track_id is not None and str(track.persistentID() or "") != track_id):
                return None
            artworks = track.artworks()
            if not len(artworks):
                return None
            data = artworks[0].rawData().get().data()
            return bytes(data) if data else None
        except Exception:
            return None
