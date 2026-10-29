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

# Playlists directly inside Bot/<category> (same folder resolution as SHUFFLE_FOLDER).
BOT_CATEGORY_PLAYLISTS = """
on run argv
    set folderName to item 1 of argv
    set parentName to item 2 of argv
    set AppleScript's text item delimiters to linefeed
    set out to {}
    tell application "Music"
        repeat with f in (every folder playlist whose name is folderName)
            try
                if name of parent of f is parentName then
                    -- f is a loop reference (item N of ...), so `parent of p is f` never matches;
                    -- compare persistent IDs instead. Prefilter by name prefix (Bot names start
                    -- with their category) so we don't walk the whole library (~5s vs ~0.3s).
                    set fid to persistent ID of f
                    repeat with p in (every user playlist whose name starts with folderName)
                        try
                            if persistent ID of parent of p is fid then set end of out to name of p
                        end try
                    end repeat
                    exit repeat
                end if
            end try
        end repeat
    end tell
    return out as text
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

# Folder path helpers shared by list/years/play-by-folder scripts (two parent levels when present).
_FOLDER_PATH = """
            set folderPath to ""
            try
                set folderPath to name of parent of p
                try
                    set folderPath to name of parent of parent of p & "/" & folderPath
                end try
            end try
"""

# Play the playlist whose name and folder path both match (user or subscription).
PLAY_PLAYLIST_IN_FOLDER = f"""
on run argv
    set playlistName to item 1 of argv
    set wantFolder to item 2 of argv
    tell application "Music"
        repeat with p in (every user playlist whose name is playlistName)
{_FOLDER_PATH}
            if folderPath is wantFolder then
                play p
                return
            end if
        end repeat
        repeat with p in (every subscription playlist whose name is playlistName)
{_FOLDER_PATH}
            if folderPath is wantFolder then
                play p
                return
            end if
        end repeat
    end tell
    error "No playlist " & playlistName & " in folder " & wantFolder
end run
"""

# One line per playlist: folderPath \\t name (subscription = Apple curated).
LIST_SUBSCRIPTION_FOLDERS = f"""
on run argv
    set out to ""
    tell application "Music"
        repeat with p in (every subscription playlist)
{_FOLDER_PATH}
            set out to out & folderPath & tab & name of p & linefeed
        end repeat
    end tell
    return out
end run
"""

# One line per user playlist: folderPath \\t name.
LIST_USER_FOLDERS = f"""
on run argv
    set out to ""
    tell application "Music"
        repeat with p in (every user playlist)
{_FOLDER_PATH}
            set out to out & folderPath & tab & name of p & linefeed
        end repeat
    end tell
    return out
end run
"""

# One line per Apple-curated playlist: folder path, name, then comma-separated track years.
SUBSCRIPTION_YEARS = f"""
on run argv
    set out to ""
    tell application "Music"
        repeat with p in (every subscription playlist)
{_FOLDER_PATH}
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
