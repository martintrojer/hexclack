"""Configurable stations: [music.stations] aliases resolve to URLs at load time and in sd-music."""

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from hexclack import config
from hexclack.music import actions, applescript, stations

URL = "https://music.apple.com/gb/station/custom/ra.123"
OTHER = "https://music.apple.com/gb/station/other/ra.456"


def doc(key: dict[str, Any], music: object = None) -> dict[str, Any]:
    raw: dict[str, Any] = {"pages": ["home"], "screens": {"home": {"kind": "page", "keys": {"1,1": key}}}}
    if music is not None:
        raw["music"] = music
    return raw


def station(name: str) -> dict[str, Any]:
    return {"music": {"action": "station", "name": name}}


def test_station_alias_resolves_to_url_everywhere() -> None:
    cfg = config.parse(
        doc(
            {"tap": station("mine"), "hold": station("other")},
            {"stations": {"mine": URL, "other": OTHER}},
        )
    )
    assert cfg.stations == {"mine": URL, "other": OTHER}
    gestures = cfg.screens["home"].keys["1,1"].gestures
    assert gestures["tap"].fields == {"action": "station", "name": "mine", "url": URL}
    assert gestures["hold"].fields["url"] == OTHER

    toggle = {"toggle": {"states": [{"label": "A", **station("mine")}, {"label": "B", **station("other")}]}}
    states = config.parse(doc(toggle, {"stations": {"mine": URL, "other": OTHER}})).screens["home"].keys["1,1"].toggle
    assert [s.action.fields["url"] for s in states] == [URL, OTHER]


def test_no_music_table_means_no_stations() -> None:
    assert config.parse(doc({"title": "x"})).stations == {}
    with pytest.raises(config.ConfigError, match="unknown station 'mine'; known: none"):
        config.parse(doc(station("mine")))


@pytest.mark.parametrize(
    ("music", "message"),
    [
        ({"stations": {"a": URL}, "extra": 1}, r"music: unknown field\(s\): extra"),
        ("nope", "music: must be a table"),
        ({"stations": ["a"]}, "music.stations: must be a table"),
        ({"stations": {"a": 1}}, "music.stations.a: must be a string URL"),
        ({"stations": {"a": "ra.123"}}, "music.stations.a: must be a full https://music.apple.com"),
        ({"stations": {"a": "http://music.apple.com/x"}}, "must be a full https"),
        ({"stations": {"a": "https://evil.example/x"}}, "must be a full https"),
        ({"stations": {"a": "https://music.apple.com/"}}, "must be a full https"),
    ],
)
def test_bad_music_table_fails(music: object, message: str) -> None:
    with pytest.raises(config.ConfigError, match=message):
        config.parse(doc({"title": "x"}, music))


def test_unknown_alias_lists_configured() -> None:
    with pytest.raises(config.ConfigError, match="unknown station 'nope'; known: mine"):
        config.parse(doc(station("nope"), {"stations": {"mine": URL}}))


def test_music_action_opens_resolved_url(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(stations, "osascript", lambda *a, **_k: calls.append(a) or "")
    action = config.parse(doc(station("mine"), {"stations": {"mine": URL}})).screens["home"].keys["1,1"].action
    assert action is not None
    actions.run(action.fields)
    assert calls == [(applescript.OPEN_URL, URL)]


def test_play_station_uses_explicit_map(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(stations, "osascript", lambda *a, **_k: calls.append(a) or "")
    stations.play_station("mine", {"mine": URL})
    assert calls == [(applescript.OPEN_URL, URL)]


def sd_music(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hexclack.music.cli", *args], capture_output=True, text=True, check=False
    )


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(body)
    return path


GOOD = f'pages = ["home"]\n[screens.home]\nkind = "page"\n[music.stations]\nmine = "{URL}"\n'


def test_cli_unknown_station_is_invalid_choice(tmp_path: Path) -> None:
    result = sd_music("--config", str(write_config(tmp_path, GOOD)), "station", "nope")
    assert result.returncode == 2
    assert "argument alias: invalid choice: 'nope' (choose from 'mine')" in result.stderr


def test_cli_missing_config_is_a_clean_error(tmp_path: Path) -> None:
    result = sd_music("--config", str(tmp_path / "missing.toml"), "station", "mine")
    assert result.returncode == 1
    assert "config:" in result.stderr and "file not found" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_invalid_config_is_a_clean_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, GOOD.replace(URL, "nope"))
    result = sd_music("--config", str(path), "list")
    assert result.returncode == 1
    assert "music.stations.mine: must be a full https://music.apple.com" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_other_commands_do_not_need_config(tmp_path: Path) -> None:
    # parse_args alone: a missing config must not stop playlist/bot/stale.
    from hexclack.music import cli

    missing = str(tmp_path / "missing.toml")
    for argv in (["playlist", "x"], ["bot", "Jazz", "latest"], ["stale"]):
        assert cli.parse_args(["--config", missing, *argv]).stations == {}


def test_cli_station_and_list_use_config_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from hexclack.music import cli, library

    path = str(write_config(tmp_path, GOOD))
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(stations, "osascript", lambda *a, **_k: calls.append(a) or "")
    cli.run(cli.parse_args(["--config", path, "station", "mine"]))
    assert calls == [(applescript.OPEN_URL, URL)]

    monkeypatch.setattr(library, "osascript", lambda *_a, **_k: "Jazz\nBeats")
    cli.run(cli.parse_args(["--config", path, "list"]))
    assert capsys.readouterr().out == "stations: mine\nbot categories: Jazz, Beats\n"


def test_cli_help_mentions_config() -> None:
    result = sd_music("--help")
    assert result.returncode == 0
    assert "--config" in result.stdout and "config.toml" in result.stdout
