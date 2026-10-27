# Apple Music

Deck actions and `sd-music` share the same music implementation. Music playback uses AppleScript; the daemon's live widget also uses ScriptingBridge and macOS notifications.

## CLI

```sh
sd-music playlist 'Example Playlist'
sd-music --config ~/.config/hexclack/config.toml station mine
sd-music --config ~/.config/hexclack/config.toml list
sd-music --config ~/.config/hexclack/config.toml explore curated
sd-music --config ~/.config/hexclack/config.toml explore saved
sd-music bot Jazz latest
sd-music bot Jazz shuffle
sd-music stale --years 2
```

`station`, `list`, and `explore` use the `[music]` tables in the selected config. There are no built-in personal station IDs. The other commands do not require a deck layout/config file. See [config.md](config.md) for stations, favourites, and browse blacklists.

## Music pad

Typical Music page (after Home): **Stations**, **Favourites**, **Saved**, **Bot**, **Explore**.

| Key | Behaviour |
| --- | --- |
| Stations | Hardcoded `[music.stations]` aliases |
| Favourites | Opens an ephemeral list of `[music.curated].favourites` (tap a name to play) |
| Saved | Explore **user** playlists by top-level folder (blacklist; Any = random) |
| Bot | Dated Bot category folders (tap latest / hold shuffle / double list) |
| Explore | Explore **subscription** (Apple curated) playlists by top-level folder |

Playlist names refer to your Music library. Bot actions assume category folders under a folder named `Bot`; `latest` selects the newest playlist with a trailing date such as `Jazz 2026 October 2`, `shuffle` plays the category folder, and `list` queries Music for dated playlists in that category and opens an ephemeral deck page (newest first; keys show metadata / month-day / year on separate rows, metadata capped; Next when needed; Home clears it). A name that ends in `Month D` without a year is renamed in Music to insert the current year, then listed.

Favourites and Bot list pages share the same ephemeral chrome (Home, items, Next). Explore/Saved open a category page (Home, **Any**, folder names, Next). Category or Any plays a random playlist in that pool with shuffle off. Busy-dim covers the AppleScript wait. Defaults blacklist personal mixes and `Now/History`/`Demo` for curated, and `Bot`/`Demo` for saved; config lists extend those defaults.

`stale` ranks Apple-curated playlists by the share of dated tracks released within the selected number of calendar years, then median year. It skips weekly personal mixes and `Now/History` folders by convention. Missing/zero years are ignored. Library names and years are read locally and are not sent to hexclack services.

## Live widgets

- `now-playing` shows artwork while playing and a dimmed cover while paused.
- `now-playing-love` follows the current track's favourite state.
- Action feedback is displayed immediately, then reconciled with Music's real state.
- Notifications are debounced; a settle read corrects transient transport state.
- Polling should not launch Music. Timeouts and automation failures become action errors rather than terminating the daemon.

macOS may ask for Automation permission to control Music. Artwork is fetched at runtime and is not distributed in this repository.
