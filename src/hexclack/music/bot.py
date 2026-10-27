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


def playlist_label(name: str) -> str:
    """Short key label from the date suffix, e.g. 'Oct 2'; undated names unchanged."""
    d = playlist_date(name)
    if d is None:
        return name
    return f"{d.strftime('%b')} {d.day}"


def dated_playlists(category: str) -> list[str]:
    """Dated playlists whose names start with category, newest first.

    Same-date ties prefer the lexicographically greater name (matches the old
    max((date, name)) pick used by latest_playlist).
    """
    names = osascript(PLAYLISTS_STARTING_WITH, category).splitlines()
    dated = [(d, name) for name in names if (d := playlist_date(name)) is not None]
    dated.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [name for _d, name in dated]


def page_items(names: list[str], page: int, capacity: int) -> tuple[list[str], bool]:
    """Slice names for one deck page.

    capacity is how many playlist slots exist when Next takes a chrome slot.
    free = capacity + 1 slots after Home can hold playlists or Next. A last page
    with remaining <= free shows all remaining and has_next False.
    """
    if capacity < 1 or page < 0:
        return [], False
    free = capacity + 1
    start = 0
    current = 0
    while True:
        remaining = len(names) - start
        if remaining <= 0:
            return [], False
        if remaining <= free:
            items, has_next = names[start:], False
        else:
            items, has_next = names[start : start + capacity], True
        if current == page:
            return items, has_next
        if not has_next:
            return [], False
        start += capacity
        current += 1


def latest_playlist(category: str) -> str:
    """Return the newest dated playlist whose name starts with the category."""
    names = dated_playlists(category)
    if not names:
        raise MusicError(f"No dated playlists for {category!r}")
    return names[0]


def play_bot(category: str, mode: Literal["latest", "shuffle"]) -> None:
    if mode == "latest":
        osascript(PLAY_LATEST, latest_playlist(category))
    else:
        osascript(SHUFFLE_FOLDER, category, BOT_FOLDER)
