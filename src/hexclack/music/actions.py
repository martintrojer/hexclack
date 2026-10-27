"""Map a config `music` table to a call (docs/music.md section 2). The only music module hexclack.actions imports."""

from collections.abc import Mapping
from typing import Literal, cast

from hexclack.music import browse, transport
from hexclack.music.bot import dated_playlists, play_bot
from hexclack.music.errors import MusicError
from hexclack.music.library import play_playlist
from hexclack.music.stations import play_url


def run(spec: Mapping[str, object]) -> dict[str, object] | None:
    """Run one validated music action. Raises MusicError on failure.

    Returns what the action changed when Music itself is slow to report it ({"favorited": bool},
    {"state": "playing"|"paused"}, {"playlist_list": ...}, or {"category_list": ...}), so the
    live keys / ephemeral lists can react at once.
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
                return {
                    "playlist_list": {
                        "label": category,
                        "entries": [{"name": n} for n in names],
                        "dated": True,
                    }
                }
            play_bot(category, cast(Literal["latest", "shuffle"], mode))
        case "favourites":
            raw_entries = spec.get("entries", [])
            entries: list[dict[str, str]] = []
            if isinstance(raw_entries, list):
                for item in raw_entries:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name")
                    if not isinstance(name, str) or not name:
                        continue
                    entry: dict[str, str] = {"name": name}
                    icon = item.get("icon")
                    if isinstance(icon, str) and icon:
                        entry["icon"] = icon
                    entries.append(entry)
            if not entries:
                raise MusicError("No favourite playlists configured")
            return {"playlist_list": {"label": "Favourites", "entries": entries, "dated": False}}
        case "explore":
            source = cast(browse.BrowseSource, str(spec["source"]))
            raw_folders = spec.get("blacklist_folders", [])
            raw_bl = spec.get("blacklist_names", [])
            folders = [f for f in raw_folders if isinstance(f, str)] if isinstance(raw_folders, list) else []
            bl_names = [n for n in raw_bl if isinstance(n, str)] if isinstance(raw_bl, list) else []
            groups = browse.browse_groups(source, folders, bl_names)
            order = browse.category_order(groups)
            return {
                "category_list": {
                    "label": "Curated" if source == "curated" else "Mine",
                    "groups": groups,
                    "order": order,
                }
            }
        case "random_playlist":
            raw_names = spec["names"]
            names = [n for n in raw_names if isinstance(n, str) and n] if isinstance(raw_names, list) else []
            browse.play_named(browse.pick_random(names))
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
