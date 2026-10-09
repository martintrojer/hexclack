"""Config validation. A bad config that loads silently would only fail when a key is pressed."""

from pathlib import Path

import pytest

from hexclack import config

ROOT = Path(__file__).parent.parent
BAD = sorted((ROOT / "tests/data").glob("bad_*.toml"))


def expected_message(path: Path) -> str:
    first = path.read_text().splitlines()[0]
    assert first.startswith("# expect: "), f"{path.name} lacks an '# expect:' line"
    return first.removeprefix("# expect: ")


def test_full_layout_loads() -> None:
    cfg = config.load(ROOT / "tests/data/layout.toml")
    assert cfg.pages == ("utils", "home", "music")
    assert len(cfg.screens) == 12
    assert sum(len(s.keys) for s in cfg.screens.values()) == 59  # 57 migrated + server health + sensor sensors


def test_example_config_loads() -> None:
    cfg = config.load(ROOT / "examples/config.toml")
    assert cfg.pages == ("home", "tools")
    assert len(cfg.screens) == 2


def test_there_are_bad_fixtures() -> None:
    assert len(BAD) >= 20


@pytest.mark.parametrize("path", BAD, ids=[p.stem for p in BAD])
def test_bad_config_fails_with_its_message(path: Path) -> None:
    with pytest.raises(config.ConfigError) as err:
        config.load(path)
    assert expected_message(path) in str(err.value)


def test_errors_name_the_screen_and_key() -> None:
    with pytest.raises(config.ConfigError, match=r'screens\.home\.keys\."1,1"'):
        config.load(ROOT / "tests/data/bad_two_actions.toml")


def test_missing_file() -> None:
    with pytest.raises(config.ConfigError, match="file not found"):
        config.load(ROOT / "tests/data/does-not-exist.toml")
