"""AppleScript sources and the osascript runner. Values reach scripts through argv, so names never need quoting."""

import subprocess

from hexclack.music.errors import MusicError

TIMEOUT_S = 10  # Music can hang on a modal dialog; a stuck worker would otherwise leak

PLAY_PLAYLIST = """
on run argv
    tell application "Music" to play playlist (item 1 of argv)
end run
"""

OPEN_URL = """
on run argv
    open location (item 1 of argv)
end run
"""

PLAYLISTS_STARTING_WITH = """
on run argv
    set AppleScript's text item delimiters to linefeed
    tell application "Music"
        return (name of every user playlist whose name starts with (item 1 of argv)) as text
    end tell
end run
"""

PLAY_LATEST = """
on run argv
    tell application "Music"
        set shuffle enabled to false
        play user playlist (item 1 of argv)
    end tell
end run
"""

RENAME_PLAYLIST = """
on run argv
    tell application "Music"
        set name of user playlist (item 1 of argv) to (item 2 of argv)
    end tell
end run
"""

SHUFFLE_FOLDER = """
on run argv
    set folderName to item 1 of argv
    set parentName to item 2 of argv
    tell application "Music"
        repeat with f in (every folder playlist whose name is folderName)
            try
                if name of parent of f is parentName then
                    set shuffle mode to songs
                    set shuffle enabled to true
                    play f
                    return
                end if
            end try
        end repeat
    end tell
    error "No folder " & parentName & "/" & folderName
end run
"""

BOT_CATEGORIES = """
on run argv
    set AppleScript's text item delimiters to linefeed
    set out to {}
    tell application "Music"
        repeat with f in (every folder playlist)
            try
                if name of parent of f is (item 1 of argv) then set end of out to name of f
            end try
        end repeat
    end tell
    return out as text
end run
"""

# One line per Apple-curated playlist: folder path, name, then comma-separated track years.
SUBSCRIPTION_YEARS = """
on run argv
    set out to ""
    tell application "Music"
        repeat with p in (every subscription playlist)
            set folderPath to ""
            try
                set folderPath to name of parent of p
                set folderPath to name of parent of parent of p & "/" & folderPath
            end try
            set AppleScript's text item delimiters to ","
            set out to out & folderPath & tab & name of p & tab & ((year of every track of p) as text) & linefeed
        end repeat
    end tell
    return out
end run
"""


def osascript(script: str, *args: str, timeout: float = TIMEOUT_S) -> str:
    """Run an AppleScript with positional arguments and return its output. Raises MusicError."""
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-", *args],
            input=script,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as err:
        raise MusicError("osascript timed out") from err
    if result.returncode != 0:
        raise MusicError(f"osascript failed: {result.stderr.strip()}")
    return result.stdout.strip()
