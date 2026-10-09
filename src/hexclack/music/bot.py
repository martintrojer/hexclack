"""Bot playlists: dated playlists inside category folders under Music's Bot folder."""

import re
from datetime import date, datetime
from typing import Literal

from hexclack.music.applescript import PLAY_LATEST, PLAYLISTS_STARTING_WITH, SHUFFLE_FOLDER, osascript
from hexclack.music.errors import MusicError

BOT_FOLDER = "Bot"
# Bot playlists end in a date such as "2026 October 2".
DATED = re.compile(r" (\d{4} [A-Z][a-z]+ \d{1,2})$")


def playlist_date(name: str) -> date | None:
    """Return the date at the end of a Bot playlist name, if it has one."""
    match = DATED.search(name)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y %B %d").date()
    except ValueError:
        return None


def latest_playlist(category: str) -> str:
    """Return the newest dated playlist whose name starts with the category."""
    names = osascript(PLAYLISTS_STARTING_WITH, category).splitlines()
    dated = [(d, name) for name in names if (d := playlist_date(name)) is not None]
    if not dated:
        raise MusicError(f"No dated playlists for {category!r}")
    return max(dated)[1]


def play_bot(category: str, mode: Literal["latest", "shuffle"]) -> None:
    if mode == "latest":
        osascript(PLAY_LATEST, latest_playlist(category))
    else:
        osascript(SHUFFLE_FOLDER, category, BOT_FOLDER)
