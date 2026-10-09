"""Apple Music stations. Aliases and their URLs come from the config's [music.stations] table."""

from collections.abc import Mapping

from hexclack.music.applescript import OPEN_URL, osascript
from hexclack.music.errors import MusicError


def play_url(url: str) -> None:
    osascript(OPEN_URL, url)


def play_station(alias: str, stations: Mapping[str, str] | None = None) -> None:
    stations = stations or {}
    url = stations.get(alias)
    if url is None:
        raise MusicError(f"Unknown station {alias!r}; known: {', '.join(stations) or 'none'}")
    play_url(url)
