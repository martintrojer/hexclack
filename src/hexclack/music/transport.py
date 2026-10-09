"""Player controls for the Home keys: play/pause, next, previous, shuffle, love (docs/music.md section 5).

AppleScript through osascript, on the action worker pool. Spike s11: `shuffle enabled` reads back
the old value for about 1 s after a change, so toggle_shuffle() never trusts an immediate read; it
reads once, writes the explicit opposite, and returns what it wrote. Spike s04: `favorited` reads
back at once by both ScriptingBridge and AppleScript; this module uses AppleScript so the CLI and
actions need no pyobjc.
"""

from hexclack.music.applescript import osascript

PLAYPAUSE = 'tell application "Music" to playpause'
NEXT = 'tell application "Music" to next track'
PREVIOUS = 'tell application "Music" to previous track'
GET_SHUFFLE = 'tell application "Music" to get shuffle enabled'
SET_SHUFFLE = """
on run argv
    tell application "Music" to set shuffle enabled to ((item 1 of argv) is "true")
end run
"""
# Measured: Music applies a favorited write asynchronously, and reads (AppleScript and ScriptingBridge)
# return the OLD value for ~10 s. So never trust a read-back: read once, write the explicit opposite,
# and report what was written.
GET_FAVORITED = 'tell application "Music" to get favorited of current track'
SET_FAVORITED = """
on run argv
    tell application "Music" to set favorited of current track to ((item 1 of argv) is "true")
end run
"""
GET_STATE = 'tell application "Music" to get player state'


def play_pause() -> str:
    """Toggle play/pause and return the state it moves to ("playing" or "paused"), computed from the
    state before the press: a read right after the change can still see the old state."""
    before = osascript(GET_STATE)
    osascript(PLAYPAUSE)
    return "paused" if before == "playing" else "playing"


def next_track() -> None:
    osascript(NEXT)


def previous_track() -> None:
    osascript(PREVIOUS)


def toggle_shuffle() -> bool:
    """Flip shuffle and return the new value (what was written, not a read-back)."""
    new = osascript(GET_SHUFFLE) != "true"
    osascript(SET_SHUFFLE, "true" if new else "false")
    return new


def toggle_favorited() -> bool:
    """Flip Favourite (`favorited`; the old `loved` property is gone, R4) and return the new value."""
    new = osascript(GET_FAVORITED) != "true"
    osascript(SET_FAVORITED, "true" if new else "false")
    return new
