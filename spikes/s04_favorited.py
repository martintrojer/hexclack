"""Spike s04 (design item 4): can we write `favorited` on the current track, by ScriptingBridge and by AppleScript?

Flips favorited, reads it back, then restores the original value, for each path.
"""

import subprocess

import ScriptingBridge


def osa(script: str) -> str:
    return subprocess.run(
        ["/usr/bin/osascript", "-e", script], capture_output=True, text=True, check=False
    ).stdout.strip()


app = ScriptingBridge.SBApplication.applicationWithBundleIdentifier_("com.apple.Music")
track = app.currentTrack()
name, original = track.name(), bool(track.favorited())
print(f"track {name!r} favorited={original}")

track.setFavorited_(not original)
sb_read = bool(app.currentTrack().favorited())
osa_read_after_sb = osa('tell application "Music" to get favorited of current track')
track.setFavorited_(original)
sb_restored = bool(app.currentTrack().favorited())
print(f"ScriptingBridge: wrote {not original}, read {sb_read}, osascript {osa_read_after_sb}, restored {sb_restored}")

osa(f'tell application "Music" to set favorited of current track to {str(not original).lower()}')
as_read = osa('tell application "Music" to get favorited of current track')
osa(f'tell application "Music" to set favorited of current track to {str(original).lower()}')
as_restored = osa('tell application "Music" to get favorited of current track')
print(f"AppleScript: wrote {not original}, read {as_read}, restored -> {as_restored}")

sb_ok = sb_read == (not original) and sb_restored == original
as_ok = as_read == str(not original).lower() and as_restored == str(original).lower()
print(f"RESULT bridge={'PASS' if sb_ok else 'FAIL'} applescript={'PASS' if as_ok else 'FAIL'}")
