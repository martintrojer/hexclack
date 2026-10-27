"""Dated Bot playlist list helpers (ephemeral category pages)."""

import pytest

from hexclack.music import bot
from hexclack.music.errors import MusicError


def test_playlist_label_from_date_suffix() -> None:
    assert bot.playlist_label("Jazz 2026 October 2") == "2026 Oct 2"
    assert bot.playlist_label("Beats DNA 2025 January 17") == "DNA 2025 Jan 17"
    assert bot.playlist_label("Songwriters Dire Straits 2026 October 26") == "Dire Straits 2026 Oct 26"
    assert bot.playlist_label("Laidback Easy Going 2026 February 9") == "Easy Going 2026 Feb 9"


def test_playlist_extra_between_category_and_date() -> None:
    assert bot.playlist_extra("Jazz DNA 2026 September 28") == "DNA"
    assert bot.playlist_extra("Beats 2026 October 23") is None
    assert bot.playlist_extra("Jazz notes") is None


def test_playlist_label_undated_unchanged() -> None:
    assert bot.playlist_label("Jazz notes") == "Jazz notes"


def test_name_with_year_inserts_before_month_day() -> None:
    assert bot.name_with_year("Beats October 23", 2026) == "Beats 2026 October 23"
    assert bot.name_with_year("Jazz DNA February 16", 2025) == "Jazz DNA 2025 February 16"
    assert bot.name_with_year("Beats 2026 October 23", 2026) is None
    assert bot.name_with_year("Jazz Essentials", 2026) is None


def test_dated_playlists_repairs_missing_year(monkeypatch: pytest.MonkeyPatch) -> None:
    from hexclack.music.applescript import PLAYLISTS_STARTING_WITH, RENAME_PLAYLIST

    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake(script: str, *args: str) -> str:
        calls.append((script, args))
        if script == RENAME_PLAYLIST:
            return ""
        return "Jazz October 2\nJazz 2025 December 31\nJazz notes"

    monkeypatch.setattr(bot, "osascript", fake)
    assert bot.dated_playlists("Jazz", repair_year=2026) == [
        "Jazz 2026 October 2",
        "Jazz 2025 December 31",
    ]
    assert (RENAME_PLAYLIST, ("Jazz October 2", "Jazz 2026 October 2")) in calls
    assert calls[0][0] == PLAYLISTS_STARTING_WITH


def test_page_items_five_fit_without_next() -> None:
    names = [f"n{i}" for i in range(5)]
    items, has_next = bot.page_items(names, 0, capacity=4)
    assert items == names
    assert has_next is False


def test_page_items_six_needs_next() -> None:
    names = [f"n{i}" for i in range(6)]
    page0, has0 = bot.page_items(names, 0, capacity=4)
    page1, has1 = bot.page_items(names, 1, capacity=4)
    assert page0 == names[:4]
    assert has0 is True
    assert page1 == names[4:]
    assert has1 is False


def test_page_items_past_end_empty() -> None:
    assert bot.page_items(["a"], 1, capacity=4) == ([], False)


def test_page_items_empty_names() -> None:
    assert bot.page_items([], 0, capacity=4) == ([], False)


def test_dated_playlists_filters_sorts_and_ties(monkeypatch: pytest.MonkeyPatch) -> None:
    names = "\n".join(
        [
            "Jazz notes",
            "Jazz 2026 Septober 1",  # bad month ignored
            "Jazz B 2026 October 2",
            "Jazz A 2026 October 2",  # same day: greater name first
            "Jazz 2026 October 1",
            "Jazz 2025 December 31",
        ]
    )
    monkeypatch.setattr(bot, "osascript", lambda *_a, **_k: names)
    assert bot.dated_playlists("Jazz") == [
        "Jazz B 2026 October 2",
        "Jazz A 2026 October 2",
        "Jazz 2026 October 1",
        "Jazz 2025 December 31",
    ]


def test_latest_playlist_uses_dated_playlists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bot,
        "osascript",
        lambda *_a, **_k: "Jazz 2026 October 1\nJazz DNA 2026 October 2",
    )
    assert bot.latest_playlist("Jazz") == "Jazz DNA 2026 October 2"


def test_latest_playlist_none_dated_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot, "osascript", lambda *_a, **_k: "Jazz notes")
    with pytest.raises(MusicError, match="No dated playlists"):
        bot.latest_playlist("Jazz")
