"""sd-music parity with the old script. A drift here changes what a key plays without any error."""

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from hexclack.music import applescript, bot, stale, stations
from hexclack.music.errors import MusicError

DATA = Path(__file__).parent / "data"


def test_format_stale_matches_old_print_stale() -> None:
    # Synthetic years: zero/unknown years and personal/history mixes do not contribute.
    rows = stale.parse_years((DATA / "subscription_years.txt").read_text(), years_back=2, today=date(2026, 10, 5))
    assert "\n".join(stale.format_stale(rows)) + "\n" == (DATA / "stale_expected.txt").read_text()


def test_personal_mixes_are_skipped() -> None:
    rows = stale.parse_years("\tNew Music\t2026,2026\nLibrary\tKept\t2026\n", years_back=2, today=date(2026, 10, 5))
    assert [r.name for r in rows] == ["Kept"]


def test_unknown_station_exit_matches_old_script() -> None:
    # The old script rejects this in argparse: exit 2 and an "invalid choice" usage error.
    result = subprocess.run(
        [sys.executable, "-m", "hexclack.music.cli", "--config", str(DATA / "layout.toml"), "station", "nope"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "argument alias: invalid choice: 'nope'" in result.stderr


def test_unknown_station_raises_instead_of_exiting() -> None:
    # The daemon imports play_station; a SystemExit there would kill it.
    with pytest.raises(MusicError, match="Unknown station 'nope'"):
        stations.play_station("nope")


def test_osascript_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 1, "", "boom\n")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(MusicError, match="osascript failed: boom"):
        applescript.osascript("return 1")


def test_osascript_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("osascript", 10)

    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(MusicError, match="timed out"):
        applescript.osascript("return 1")


def test_latest_playlist_picks_newest_date(monkeypatch: pytest.MonkeyPatch) -> None:
    names = "Jazz DNA 2026 September 28\nJazz DNA 2026 October 2\nJazz DNA notes\nJazz DNA 2026 Septober 9"
    monkeypatch.setattr(bot, "osascript", lambda *_a, **_k: names)
    assert bot.latest_playlist("Jazz") == "Jazz DNA 2026 October 2"


def test_latest_playlist_none_dated_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot, "osascript", lambda *_a, **_k: "Jazz notes")
    with pytest.raises(MusicError, match="No dated playlists for 'Jazz'"):
        bot.latest_playlist("Jazz")


def test_bot_list_mode_returns_names(monkeypatch: pytest.MonkeyPatch) -> None:
    from hexclack.music import actions as music_actions

    monkeypatch.setattr(
        bot,
        "osascript",
        lambda *_a, **_k: "Jazz 2026 October 1\nJazz 2026 October 2\nJazz notes",
    )
    assert music_actions.run({"action": "bot", "category": "Jazz", "mode": "list"}) == {
        "bot_list": {
            "category": "Jazz",
            "names": ["Jazz 2026 October 2", "Jazz 2026 October 1"],
        }
    }


def test_bot_list_mode_empty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from hexclack.music import actions as music_actions

    monkeypatch.setattr(bot, "osascript", lambda *_a, **_k: "Jazz notes")
    with pytest.raises(MusicError, match="No dated playlists for 'Jazz'"):
        music_actions.run({"action": "bot", "category": "Jazz", "mode": "list"})


def test_cli_does_not_import_bridge_or_pillow() -> None:
    # sd-music must start fast and not load the daemon's GUI dependencies (music.md section 3).
    code = "import sys, hexclack.music.cli; print('PIL' in sys.modules, 'hexclack.music.bridge' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.split() == ["False", "False"]
