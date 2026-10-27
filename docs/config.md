# Configuration

hexclack reads `~/.config/hexclack/config.toml` by default. Copy [the starter](../examples/config.toml) there and edit that private copy. `hexclack run --config PATH`, `hexclack render --config PATH --all`, and `hexclack check-config PATH` select another file.

There is one TOML document, no interpolation or overlay mechanism. Real hosts, recipients, playlist names and account-specific station URLs belong in your private document, not the public example. Passwords belong in Keychain. Icons are relative to the config file's directory; keep your own artwork beside it.

Unknown fields, wrong types and dangling navigation/station references are rejected at load time. Validate before running:

```sh
hexclack check-config
```

## Top-level schema

| Field/table | Meaning/default |
| --- | --- |
| `pages` | Required non-empty ordered list of all page screen names |
| `screens.NAME` | Required screens, with `kind = "page"` or `"folder"` |
| `device` | `brightness = 80`, `clock_minutes = 30`, `sleep_minutes = 120`, `quiet_start = 22`, `quiet_end = 6`; zero disables the relevant idle transition |
| `gestures` | `double_ms = 300`, `hold_ms = 500` |
| `watchdog` | `interval_s = 10`, `health_timeout_s = 2`, `uhubctl = false`, `uhubctl_location = ""` |
| `secrets` | `pihole_service = "hexclack-pihole"` (Keychain service name, not a password) |
| `music.stations` | Optional alias-to-full-Apple-Music-URL map; empty by default |
| `music.curated` | Optional `favourites` list and explore `blacklist_folders` / `blacklist_names` |
| `music.saved` | Optional explore `blacklist_folders` / `blacklist_names` for user playlists |
| `auto_brightness` | Optional sensor URL and increasing `[light, percent]` pairs |

Clock time must precede sleep time when both are enabled. Past sleep time an alert normally keeps the clock and its banner up; during quiet hours (from local hour `quiet_start` up to `quiet_end`, 0–23, wrapping past midnight) it does not, and the keys stay dark. Equal hours disable quiet hours. Automatic brightness uses the sensor's raw `visible_light`, not lux; percent values are 0–100. If readings fail or go stale, normal configured brightness is used.

```toml
[auto_brightness]
url = "http://sensor.example.test:8044/sensors"
points = [[0, 25], [30, 50], [200, 90], [1000, 100]]
```

## Screens and keys

Each screen has `kind`; folders also need `parent = "SCREEN"`. Keys are indexed by `"col,row"`, columns 0–2 and rows 0–1. A folder's `"0,0"` is reserved for the automatic Home key. Include a screen named `home` as your starting screen.

```toml
[screens.tools]
kind = "folder"
parent = "home"

[screens.tools.keys."1,0"]
title = "Example"
icon = "icons/example.png" # optional; no icon needed for a title-only key
shell = { cmd = "open -a Calculator" }

[screens.tools.keys."2,0"]
title = "Jazz"
tile = { glyph = "🤖", start = "#bf5af2", end = "#1f1147" }  # generated face; use title for the label
music = { action = "bot", category = "Jazz", mode = "latest" }
```

Key fields: `title`, `icon`, `tile`, `widget`, `health`, `alerts`, plus one action, gesture tables or a toggle. Use `icon` **or** `tile`, not both. `tile` is a generated gradient face (`glyph` emoji, `start`/`end` `#RRGGBB` diagonal fade); the key `title` overlays as usual. `alerts = true` adds a border when a health/sensor alert is active.

### Actions

| Action table | Fields |
| --- | --- |
| `shell` | `cmd` (runs through the shell as your user) |
| `applescript` | `script` |
| `http` | `method` (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`), `url` |
| `pihole` | `host`, integer `disable_seconds` |
| `nav` | Exactly one of `home = true`, `page = "prev"/"next"`, `folder = "NAME"` |
| `music` | `action`; see below |

Review commands before running someone else's config. Config files are executable instructions, not sandboxed data.

Music actions: `playlist` and `station` need `name`; `bot` needs a non-empty `category` and `mode = "latest"/"shuffle"/"list"` (list/latest only see playlists inside `Bot/<category>`); `favourites` needs only `action` (names come from `music.curated.favourites`); `explore` needs `source = "curated"` or `"saved"`; `play_pause`, `next`, `previous`, `shuffle`, `love` need only `action`. Mode `list` and `favourites` do not start playback; they open an ephemeral playlist page. `explore` opens an ephemeral category page (Home, Any, folders, Next); picks keep folder identity so duplicate names play the right playlist.

### Personal station URLs

Paste a full station share URL from Apple Music into your private config. The URL must be HTTPS on `music.apple.com`; it may include the storefront of your choice. The example below is a placeholder, not a playable station.

```toml
[music.stations]
mine = "https://music.apple.com/us/station/example/ra.123456"

[screens.home.keys."1,0"]
title = "My station"
music = { action = "station", name = "mine" }
```

Both deck actions and `sd-music --config PATH station mine` use this map. Station aliases are resolved when loading; an undefined alias fails validation. `sd-music list` lists configured station aliases and locally discovered Bot categories.

### Favourites and browse blacklists

```toml
[music.curated]
favourites = [
  "New Music",  # name-only: title text on the key
  { name = "Your Essentials", icon = "icons/Favourites Mix.png" },  # artwork: icon-only (no title)
  { name = "Flow State", tile = { glyph = "🌊", start = "#0a84ff", end = "#002a5c" } },  # generated face + title
]
blacklist_folders = ["Demo", "Now/History"]  # your library; no folder defaults are baked in
blacklist_names = []                          # extends baked-in Apple personal-mix names

[music.saved]
blacklist_folders = ["Demo"]          # extends baked-in Bot (keeps the Bot pad exclusive)
blacklist_names = []

[screens.music.keys."2,0"]
title = "Favourites"
music = { action = "favourites" }

[screens.music.keys."2,1"]
title = "Curated"
music = { action = "explore", source = "curated" }

[screens.music.keys."0,1"]
title = "Mine"
music = { action = "explore", source = "saved" }
```

`favourites` fails config load if the list is empty. Each entry is a playlist name string, `{ name, icon? }` (artwork path; icon-only key), or `{ name, tile? }` (generated face with title overlay). `icon` and `tile` are mutually exclusive. Curated name blacklists merge with Apple's weekly personal-mix titles; Mine folder blacklists merge with `Bot`. Other folders (`Demo`, `Now/History`, …) are config-only. Filters are stored on the action at load. `sd-music explore curated|saved` prints category sizes after filtering.

### Gestures

Instead of a key-level action, define `tap`, `double`, and/or `hold` subtables, each with one action. A double action needs a tap action too.

```toml
[screens.home.keys."2,1"]
title = "Skip"
[screens.home.keys."2,1".tap]
music = { action = "next" }
[screens.home.keys."2,1".double]
music = { action = "previous" }
[screens.home.keys."2,1".hold]
music = { action = "shuffle" }
```

### Toggles

A toggle needs at least two `states`, each with `label`, optional `icon`, and one action. Blind toggles use `initial = 0`: run the shown state's action, then advance only after success. Their state is in memory.

Status-backed toggles instead use `status = { url, field }`; each state has a distinct `value`, and `initial` is not allowed. A press sends the next state's action relative to the last polled value. Unknown/unreachable status blocks presses.

```toml
[screens.tools.keys."1,1".toggle]
status = { url = "http://device.example.test/api/state", field = "enabled" }
states = [
  { label = "Off", value = 0, http = { method = "PUT", url = "http://device.example.test/api/state?enabled=0" } },
  { label = "On", value = 1, http = { method = "PUT", url = "http://device.example.test/api/state?enabled=1" } },
]
```

### Widgets

| `widget` | Additional config |
| --- | --- |
| `now-playing` | Usually paired with music `play_pause` |
| `now-playing-love` | Usually paired with music `love` |
| `pihole-status` | A `pihole` action supplies the host |
| `health-json` | `health = { url = "http://server.example.test/health.json" }` |
| `sensors` | `health = { url = "http://sensor.example.test:8044/sensors" }` |

Health JSON contains `checked_at` (ISO-8601), `data` with a status, and `services` mapping IDs to objects with `label`, `section`, `status`. Service statuses are `healthy`, `unhealthy`, `not-installed`. Old responses are marked stale.

The sensor widget expects `age_s`, `temperature`, `relative_humidity`, `aqi_str` (ENS160 UBA air-quality description), and optionally `visible_light`. See synthetic samples in `tests/test_sensors.py` for the full response shape. These integrations expect these specific JSON formats; they are not arbitrary JSON viewers.

### Pi-hole credentials

Pi-hole v6 hosts include the port, e.g. `pihole.example.test:8000`. Store the password in Keychain under the configured service and host account. Use Keychain Access to add a generic password without placing the value in command history. The client reads it using:

```sh
security find-generic-password -s hexclack-pihole -a pihole.example.test:8000 -w
```

Do not put passwords, tokens or URL credentials in TOML. Pi-hole uses HTTP by default; use only a trusted network.
