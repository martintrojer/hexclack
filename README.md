# hexclack

A Python daemon for the Elgato Stream Deck Mini (MK2, PID `0x90`) on macOS. It drives the device directly over USB instead of using the Elgato app.

## Features

- TOML-defined pages, folders and 3×2 key layouts.
- Tap, double-tap and hold gestures.
- Shell, AppleScript, HTTP, Apple Music and Pi-hole v6 actions.
- Live now-playing artwork, favourites, Pi-hole status, health and room-sensor widgets.
- Clock screen saver, alert indicators and optional ambient-light brightness.
- Disconnect recovery, watchdog and macOS LaunchAgent installation.

macOS only; one Stream Deck Mini. Quit the Elgato app before running hexclack. A firmware wedge may still require unplugging the device; the watchdog reports this rather than hanging indefinitely.

## Setup

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/) and `libhidapi` (`brew install hidapi`).

```sh
uv sync
mkdir -p ~/.config/hexclack
cp examples/config.toml ~/.config/hexclack/config.toml
uv run hexclack check-config
uv run hexclack render --all
uv run hexclack run
```

Allow macOS Automation access when prompted to control Music. Add other actions only after reviewing their commands: shell and AppleScript actions run as your user.

To install the commands and load the background agent:

```sh
make install
hexclack status
```

`make uninstall` unloads and removes the agent. Logs live in `~/Library/Logs/hexclack/hexclack.log`.

## Configuration

See [docs/config.md](docs/config.md) for the schema and examples. The default config is `~/.config/hexclack/config.toml`; keep your real hosts, recipients, station URLs and artwork there, outside Git. Pi-hole passwords are read from macOS Keychain.

`sd-music` provides terminal commands for playlists, configured stations, Bot folders and playlist freshness. Run `sd-music --help` for usage. Station aliases are configured, not bundled account IDs.

No third-party artwork is distributed. Keys can use titles alone, local icon files or live widgets. Transport symbols are drawn by the project; other renderers use macOS system fonts and emoji at runtime.

## Development

```sh
make gate
```

The gate checks formatting, lint, types and the full test suite. Hardware probes live in `spikes/`; running them may seize the device or control Music. Tests use synthetic data and do not need an attached deck.

## License

[MIT](LICENSE), for the project's own code and synthetic test assets. User-supplied artwork and macOS system resources retain their respective owners' rights.
