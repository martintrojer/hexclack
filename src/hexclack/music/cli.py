"""Play Apple Music playlists and stations from Stream Deck buttons.

Every Stream Deck music button calls this script, so the button config only
holds a short command such as `sd-music station mine`.

Commands:
    playlist NAME           play a library playlist by name
    station ALIAS           open a station listed in the config's [music.stations]
    bot CATEGORY latest     play the newest dated playlist in Bot/CATEGORY
    bot CATEGORY shuffle    shuffle every track in the Bot/CATEGORY folder
    list                    print the station aliases and Bot categories
    stale [--years N]       rank Apple Music playlists by how recent their tracks are
    explore curated|saved   print top-level folder categories after blacklist

Only station, list, and explore read the config (--config, default ~/.config/hexclack/config.toml).
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from hexclack import config
from hexclack.music import browse
from hexclack.music.bot import play_bot
from hexclack.music.errors import MusicError
from hexclack.music.library import list_targets, play_playlist
from hexclack.music.stale import format_stale, freshness
from hexclack.music.stations import play_station

CONFIG_COMMANDS = ("station", "list", "explore")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sd-music", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=config.DEFAULT_PATH,
        help="hexclack config with [music.*] (station, list, explore; default: %(default)s)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("playlist").add_argument("name")
    station = sub.add_parser("station")
    station.add_argument("alias", help="a station alias from the config's [music.stations]")
    bot = sub.add_parser("bot")
    bot.add_argument("category")
    bot.add_argument("mode", choices=("latest", "shuffle"))
    sub.add_parser("list")
    stale = sub.add_parser("stale", help="rank curated playlists by track recency")
    stale.add_argument("--years", type=int, default=2, help="count tracks from the last N years as recent")
    explore = sub.add_parser("explore", help="list top-level folders for curated or saved browse")
    explore.add_argument("source", choices=("curated", "saved"))
    args = parser.parse_args(argv)
    args.stations = {}
    args.curated = config.CuratedMusic()
    args.saved = config.SavedMusic()
    if args.command in CONFIG_COMMANDS:
        try:
            cfg = config.load(args.config)
            args.stations = cfg.stations
            args.curated = cfg.curated
            args.saved = cfg.saved
        except config.ConfigError as err:
            parser.exit(1, f"{parser.prog}: error: config: {err}\n")
    if args.command == "station" and args.alias not in args.stations:
        choices = ", ".join(map(repr, args.stations)) or "none configured"
        station.error(f"argument alias: invalid choice: {args.alias!r} (choose from {choices})")
    return args


def run(args: argparse.Namespace) -> None:
    match args.command:
        case "playlist":
            play_playlist(args.name)
        case "station":
            play_station(args.alias, args.stations)
        case "bot":
            play_bot(args.category, args.mode)
        case "list":
            targets = list_targets(args.stations)
            print("stations:", ", ".join(targets.stations))
            print("bot categories:", ", ".join(targets.bot_categories))
        case "stale":
            print("\n".join(format_stale(freshness(args.years))))
        case "explore":
            if args.source == "curated":
                folders = browse.merge_blacklist(browse.CURATED_DEFAULT_FOLDERS, args.curated.blacklist_folders)
                names = browse.merge_blacklist(browse.CURATED_DEFAULT_NAMES, args.curated.blacklist_names)
            else:
                folders = browse.merge_blacklist(browse.SAVED_DEFAULT_FOLDERS, args.saved.blacklist_folders)
                names = browse.merge_blacklist(browse.SAVED_DEFAULT_NAMES, args.saved.blacklist_names)
            groups = browse.browse_groups(args.source, folders, names)
            for cat in browse.category_order(groups):
                print(f"{len(groups[cat]):3d}  {cat}")


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        run(args)
    except MusicError as err:
        sys.exit(str(err))


if __name__ == "__main__":
    main()
