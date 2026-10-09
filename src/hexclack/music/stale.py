"""Rank Apple-curated playlists by how many of their tracks are recent."""

import statistics
from dataclasses import dataclass
from datetime import date

from hexclack.music.applescript import SUBSCRIPTION_YEARS, osascript

# Reading every curated playlist's track years takes about 15 s; this is a terminal command, not a key press.
STALE_TIMEOUT_S = 120

# Apple rebuilds these for you each week, so their track years say nothing about freshness.
PERSONAL_MIXES = frozenset({"Get Up!", "Your Essentials", "Heavy Rotation", "New Music", "Chill"})


@dataclass(frozen=True)
class Freshness:
    folder: str
    name: str
    recent_share: float
    median_year: int
    newest_year: int
    tracks: int


def parse_years(raw: str, years_back: int, today: date) -> list[Freshness]:
    """Score SUBSCRIPTION_YEARS output: the share of tracks released in the last years_back years."""
    cutoff = today.year - years_back + 1
    rows: list[Freshness] = []
    for line in raw.splitlines():
        folder, name, raw_years = [*line.split("\t"), "", ""][:3]
        if name in PERSONAL_MIXES or folder.startswith("Now/History"):
            continue
        years = [int(y) for y in raw_years.split(",") if y.strip().isdigit() and int(y) > 0]
        if not years:
            continue
        recent = sum(y >= cutoff for y in years) / len(years)
        rows.append(Freshness(folder, name, recent, int(statistics.median(years)), max(years), len(years)))
    return sorted(rows, key=lambda r: (r.recent_share, r.median_year), reverse=True)


def freshness(years_back: int) -> list[Freshness]:
    return parse_years(osascript(SUBSCRIPTION_YEARS, timeout=STALE_TIMEOUT_S), years_back, date.today())


def format_stale(rows: list[Freshness]) -> list[str]:
    lines = [f"{'recent':>6} {'median':>6} {'newest':>6} {'tracks':>6}  playlist"]
    for r in rows:
        where = f"{r.folder} / {r.name}" if r.folder else r.name
        lines.append(f"{r.recent_share:6.0%} {r.median_year:6} {r.newest_year:6} {r.tracks:6}  {where}")
    return lines
