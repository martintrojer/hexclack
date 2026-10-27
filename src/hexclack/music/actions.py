"""Map a config `music` table to a call (docs/music.md section 2). The only music module hexclack.actions imports."""

from collections.abc import Mapping
from typing import Literal, cast

from hexclack.music import transport
from hexclack.music.bot import dated_playlists, play_bot
from hexclack.music.errors import MusicError
from hexclack.music.library import play_playlist
from hexclack.music.stations import play_url


def run(spec: Mapping[str, object]) -> dict[str, object] | None:
    """Run one validated music action. Raises MusicError on failure.

    Returns what the action changed when Music itself is slow to report it ({"favorited": bool},
    {"state": "playing"|"paused"}, or {"bot_list": {"category", "names"}} for mode=list), so the
    live keys / ephemeral bot list can react at once.
    """
    match spec["action"]:
        case "playlist":
            play_playlist(str(spec["name"]))
        case "station":
            play_url(str(spec["url"]))  # config parsing resolved the alias to its URL
        case "bot":
            category = str(spec["category"])
            mode = str(spec["mode"])
            if mode == "list":
                names = dated_playlists(category)
                if not names:
                    raise MusicError(f"No dated playlists for {category!r}")
                return {"bot_list": {"category": category, "names": names}}
            play_bot(category, cast(Literal["latest", "shuffle"], mode))
        case "play_pause":
            return {"state": transport.play_pause()}
        case "next":
            transport.next_track()
        case "previous":
            transport.previous_track()
        case "shuffle":
            transport.toggle_shuffle()
        case "love":
            return {"favorited": transport.toggle_favorited()}
        case other:
            raise ValueError(f"unknown music action {other!r}")  # config validation makes this unreachable
    return None
