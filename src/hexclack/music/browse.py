"""Folder browse for subscription (curated) and user (saved) playlists."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from hexclack.music.applescript import LIST_SUBSCRIPTION_FOLDERS, LIST_USER_FOLDERS, osascript
from hexclack.music.errors import MusicError
from hexclack.music.stale import PERSONAL_MIXES

BrowseSource = Literal["curated", "saved"]

# Defaults: personal mixes + history for curated; Bot exclusive + Demo dump for saved.
CURATED_DEFAULT_FOLDERS = ("Now/History", "Demo")
CURATED_DEFAULT_NAMES = tuple(sorted(PERSONAL_MIXES))
SAVED_DEFAULT_FOLDERS = ("Bot", "Demo")
SAVED_DEFAULT_NAMES: tuple[str, ...] = ()

LIST_TIMEOUT_S = 120


@dataclass(frozen=True)
class PlaylistRef:
    folder: str  # full path from Music, or "" for root
    name: str

    @property
    def top_level(self) -> str:
        if not self.folder:
            return "Other"
        return self.folder.split("/", 1)[0]


def parse_folder_list(raw: str) -> list[PlaylistRef]:
    """Parse AppleScript TSV: folderPath \\t name per line."""
    rows: list[PlaylistRef] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        folder, sep, name = line.partition("\t")
        if not sep:
            continue
        name = name.strip()
        if name:
            rows.append(PlaylistRef(folder=folder.strip(), name=name))
    return rows


def is_blacklisted(
    ref: PlaylistRef,
    blacklist_folders: Sequence[str],
    blacklist_names: Sequence[str],
) -> bool:
    if ref.name in blacklist_names:
        return True
    folder = ref.folder
    for blocked in blacklist_folders:
        if folder == blocked or folder.startswith(blocked + "/") or ref.top_level == blocked:
            return True
    return False


def filter_refs(
    refs: Sequence[PlaylistRef],
    blacklist_folders: Sequence[str],
    blacklist_names: Sequence[str],
) -> list[PlaylistRef]:
    return [r for r in refs if not is_blacklisted(r, blacklist_folders, blacklist_names)]


def group_by_top_level(refs: Sequence[PlaylistRef]) -> dict[str, list[PlaylistRef]]:
    """Category -> playlist refs (stable: first-seen order; keeps same name in different folders)."""
    groups: dict[str, list[PlaylistRef]] = defaultdict(list)
    seen: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for ref in refs:
        cat = ref.top_level
        key = (ref.folder, ref.name)
        if key not in seen[cat]:
            seen[cat].add(key)
            groups[cat].append(ref)
    return dict(groups)


def category_order(groups: Mapping[str, Sequence[PlaylistRef]]) -> list[str]:
    """Largest categories first, then name."""
    return sorted(groups, key=lambda c: (-len(groups[c]), c.lower()))


def merge_blacklist(defaults: Sequence[str], extra: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for name in (*defaults, *extra):
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return tuple(out)


def list_playlists(source: BrowseSource) -> list[PlaylistRef]:
    script = LIST_SUBSCRIPTION_FOLDERS if source == "curated" else LIST_USER_FOLDERS
    return parse_folder_list(osascript(script, timeout=LIST_TIMEOUT_S))


def browse_groups(
    source: BrowseSource,
    blacklist_folders: Sequence[str],
    blacklist_names: Sequence[str],
) -> dict[str, list[PlaylistRef]]:
    refs = filter_refs(list_playlists(source), blacklist_folders, blacklist_names)
    groups = group_by_top_level(refs)
    if not groups:
        raise MusicError(f"No {source} playlists after blacklist")
    return groups
