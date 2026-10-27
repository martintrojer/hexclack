"""Library playlists and the list of playable targets."""

from collections.abc import Mapping
from dataclasses import dataclass

from hexclack.music.applescript import BOT_CATEGORIES, PLAY_PLAYLIST, PLAY_PLAYLIST_IN_FOLDER, osascript
from hexclack.music.bot import BOT_FOLDER


@dataclass(frozen=True)
class Targets:
    stations: list[str]
    bot_categories: list[str]


def play_playlist(name: str, folder: str | None = None) -> None:
    """Play by name alone, or by name+folder when folder is given (disambiguates duplicates)."""
    if folder is None:
        osascript(PLAY_PLAYLIST, name)
    else:
        osascript(PLAY_PLAYLIST_IN_FOLDER, name, folder)


def list_targets(stations: Mapping[str, str]) -> Targets:
    return Targets(stations=list(stations), bot_categories=osascript(BOT_CATEGORIES, BOT_FOLDER).splitlines())
