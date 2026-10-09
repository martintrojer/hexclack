"""Map a config `music` table to a call (docs/music.md section 2). The only music module hexclack.actions imports."""

from collections.abc import Mapping
from typing import Literal, cast

from hexclack.music import transport
from hexclack.music.bot import play_bot
from hexclack.music.library import play_playlist
from hexclack.music.stations import play_url


def run(spec: Mapping[str, object]) -> dict[str, object] | None:
    """Run one validated music action. Raises MusicError on failure.

    Returns what the action changed when Music itself is slow to report it ({"favorited": bool} or
    {"state": "playing"|"paused"}), so the live keys can show it at once.
    """
    match spec["action"]:
        case "playlist":
            play_playlist(str(spec["name"]))
        case "station":
            play_url(str(spec["url"]))  # config parsing resolved the alias to its URL
        case "bot":
            play_bot(str(spec["category"]), cast(Literal["latest", "shuffle"], spec["mode"]))
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
