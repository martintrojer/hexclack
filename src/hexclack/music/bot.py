"""Bot playlists: dated playlists inside category folders under Music's Bot folder."""

import re
from datetime import date, datetime
from typing import Literal

from hexclack.music.applescript import (
    PLAY_LATEST,
    PLAYLISTS_STARTING_WITH,
    RENAME_PLAYLIST,
    SHUFFLE_FOLDER,
    osascript,
)
from hexclack.music.errors import MusicError

BOT_FOLDER = "Bot"
# Bot playlists end in a date such as "2026 October 2".
DATED = re.compile(r" (\d{4} [A-Z][a-z]+ \d{1,2})$")
# Same convention but year omitted: "October 2" — repaired by inserting a year.
_MONTH = "January|February|March|April|May|June|July|August|September|October|November|December"
MONTH_DAY = re.compile(rf" ({_MONTH}) (\d{{1,2}})$")


def playlist_date(name: str) -> date | None:
    """Return the date at the end of a Bot playlist name, if it has one."""
    match = DATED.search(name)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y %B %d").date()
    except ValueError:
        return None


def playlist_extra(name: str) -> str | None:
    """Text between the category (first word) and the date suffix, if any.

    'Jazz DNA 2026 September 28' → 'DNA'; 'Beats 2026 October 23' → None.
    """
    match = DATED.search(name)
    if match is None:
        return None
    prefix = name[: match.start()].strip()
    parts = prefix.split(None, 1)
    return parts[1] if len(parts) > 1 else None


def playlist_label(name: str) -> str:
    """Key label: optional extra info plus date, e.g. 'DNA 2026 Sep 28' or '2026 Oct 2'."""
    d = playlist_date(name)
    if d is None:
        return name
    date_s = f"{d.year} {d.strftime('%b')} {d.day}"
    extra = playlist_extra(name)
    return f"{extra} {date_s}" if extra else date_s


def name_with_year(name: str, year: int) -> str | None:
    """Insert year before a trailing 'Month D' suffix. None if the name is not that shape."""
    if playlist_date(name) is not None:
        return None
    match = MONTH_DAY.search(name)
    if match is None:
        return None
    return f"{name[: match.start()]} {year} {match.group(1)} {match.group(2)}"


def repair_missing_year(name: str, year: int | None = None) -> str | None:
    """Rename a Music playlist that ends in Month D so it includes year. Returns the new name."""
    new_name = name_with_year(name, year if year is not None else date.today().year)
    if new_name is None:
        return None
    osascript(RENAME_PLAYLIST, name, new_name)
    return new_name


def dated_playlists(category: str, *, repair_year: int | None = None) -> list[str]:
    """Dated playlists whose names start with category, newest first.

    Same-date ties prefer the lexicographically greater name (matches the old
    max((date, name)) pick used by latest_playlist).

    Names that end in Month D without a year are renamed in Music to insert
    repair_year (default: today's year), then included.
    """
    names = osascript(PLAYLISTS_STARTING_WITH, category).splitlines()
    year = repair_year if repair_year is not None else date.today().year
    dated: list[tuple[date, str]] = []
    for name in names:
        if not name:
            continue
        d = playlist_date(name)
        if d is not None:
            dated.append((d, name))
            continue
        repaired = repair_missing_year(name, year)
        if repaired is not None and (d := playlist_date(repaired)) is not None:
            dated.append((d, repaired))
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
