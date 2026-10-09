"""hexclack command line (docs/design.md section 8)."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from hexclack import config


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="hexclack")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check-config", help="validate a config file")
    check.add_argument("path", nargs="?", type=Path, default=config.DEFAULT_PATH)
    render = sub.add_parser("render", help="draw screens to PNG grids without a device")
    render.add_argument("screen", nargs="?", help="screen name (omit with --all)")
    render.add_argument("--all", action="store_true", help="every screen in the config")
    render.add_argument("--config", type=Path, default=config.DEFAULT_PATH)
    render.add_argument("--out", type=Path, default=Path("render"))
    run = sub.add_parser("run", help="drive the deck in the foreground")
    run.add_argument("-v", "--verbose", action="store_true")
    run.add_argument("--config", type=Path, default=config.DEFAULT_PATH)
    sub.add_parser("status", help="watchdog state from state.json, and whether the Mini is attached")
    bright = sub.add_parser("brightness", help="try a brightness on the running deck for 5 minutes (tuning)")
    bright.add_argument("percent", type=int)
    sub.add_parser("install-agent", help="write and load the LaunchAgent (~/Library/LaunchAgents/com.hexclack.plist)")
    sub.add_parser("uninstall-agent", help="unload and remove the LaunchAgent")
    args = parser.parse_args(argv)

    if args.command == "check-config":
        path: Path = args.path
        try:
            cfg = config.load(path)
        except config.ConfigError as err:
            sys.exit(f"{path}: {err}")
        keys = sum(len(s.keys) for s in cfg.screens.values())
        print(f"{path}: ok ({len(cfg.screens)} screens, {keys} keys)")
        return
    if args.command == "run":
        from hexclack import lock

        lock.acquire()  # first: before state.json, notifications or the device (design section 3)
        import logging

        from hexclack import daemon

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(threadName)s %(message)s")
        if args.verbose:
            logging.getLogger("hexclack").setLevel(logging.DEBUG)  # not Pillow's or urllib's debug output
        try:
            cfg = config.load(args.config)
        except config.ConfigError as err:
            sys.exit(f"{args.config}: {err}")
        daemon.run(cfg, args.config.parent)
        return
    if args.command == "status":
        _status()
        return
    if args.command == "brightness":
        from hexclack.brightness import OVERRIDE_FILE, OVERRIDE_S

        if not 0 <= args.percent <= 100:
            sys.exit("hexclack brightness: percent must be 0-100")
        OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
        OVERRIDE_FILE.write_text(str(args.percent))
        print(f"deck at {args.percent}% for {OVERRIDE_S // 60} min (needs the running agent)")
        return
    if args.command == "render":
        _render(args.config, args.out, args.screen, args.all)
        return
    if args.command == "install-agent":
        from hexclack import agent

        try:
            path = agent.install()
        except (FileNotFoundError, RuntimeError) as err:
            sys.exit(str(err))
        print(f"installed and loaded {path}; log: {agent.log_path(Path.home())}")
        return
    if args.command == "uninstall-agent":
        from hexclack import agent

        agent.uninstall()
        print("unloaded and removed com.hexclack")
        return
    parser.error(f"unknown command {args.command}")


def _status() -> None:
    """Read-only: never opens the device, so it is safe while the daemon runs."""
    from hexclack.device import usb_serials
    from hexclack.watchdog import STATE_FILE, load_state

    state = load_state(STATE_FILE)
    serials = usb_serials()
    print(f"state: {state.state}" + ("" if STATE_FILE.exists() else " (no state.json yet)"))
    print(f"attached: {', '.join(serials) if serials else 'no Stream Deck Mini on USB'}")
    print(f"hang_exits: {state.hang_exits}" + (f" (last {state.last_exit})" if state.last_exit else ""))
    if state.notified_at:
        print(f"last replug notification: {state.notified_at}")


def _render(path: Path, out: Path, screen: str | None, every: bool) -> None:
    from hexclack import render  # Pillow is only loaded for commands that draw

    try:
        cfg = config.load(path)
    except config.ConfigError as err:
        sys.exit(f"{path}: {err}")
    if every == (screen is not None):
        sys.exit("hexclack render: give a screen name or --all, not both")
    names = list(cfg.screens) if every else [screen or ""]
    if unknown := [n for n in names if n not in cfg.screens]:
        sys.exit(f"hexclack render: unknown screen {unknown[0]!r}; screens: {', '.join(cfg.screens)}")
    for written in render.render_screens(cfg, path.parent, out, names):
        print(written)


if __name__ == "__main__":
    main()
