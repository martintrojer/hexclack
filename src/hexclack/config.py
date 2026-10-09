"""Load and validate the hexclack TOML config (docs/design.md section 5).

Validation is strict: an unknown field, a wrong type or a dangling reference fails at load time,
so a typo cannot surface later as a key that silently does nothing when pressed.
"""

import tomllib
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

DEFAULT_PATH = Path.home() / ".config/hexclack/config.toml"

COLS = 3
ROWS = 2
BACK_SLOT = "0,0"  # a folder's automatic Home key
HOME_SCREEN = "home"

ACTION_TYPES = ("shell", "applescript", "http", "music", "pihole", "nav")
GESTURES = ("tap", "double", "hold")
WIDGETS = ("now-playing", "now-playing-love", "pihole-status", "health-json", "sensors")
URL_WIDGETS = ("health-json", "sensors")  # widgets that read a `health = { url }` (GET only)
MUSIC_ACTIONS = ("playlist", "station", "bot", "play_pause", "next", "previous", "shuffle", "love")
BOT_MODES = ("latest", "shuffle")
HTTP_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH")

# Fields each action type accepts: name -> required?
ACTION_FIELDS: dict[str, dict[str, bool]] = {
    "shell": {"cmd": True},
    "applescript": {"script": True},
    "http": {"method": True, "url": True},
    "pihole": {"host": True, "disable_seconds": True},
}
MUSIC_FIELDS: dict[str, tuple[str, ...]] = {
    "playlist": ("name",),
    "station": ("name",),
    "bot": ("category", "mode"),
}

KEY_FIELDS = {"title", "icon", "widget", "toggle", "health", "alerts", *ACTION_TYPES, *GESTURES}
TOP_LEVEL = {"pages", "device", "gestures", "watchdog", "secrets", "screens", "auto_brightness", "music"}
STATION_HOST = "music.apple.com"


class ConfigError(Exception):
    """The config file is invalid. The message names the screen and key where possible."""


@dataclass(frozen=True)
class Action:
    """One action: its type (a key of ACTION_TYPES) and its fields."""

    kind: str
    fields: dict[str, Any]


@dataclass(frozen=True)
class ToggleState:
    label: str
    icon: str | None
    action: Action
    value: object = None  # with a status source: the status field value this state represents


@dataclass(frozen=True)
class Status:
    """Where a status-backed toggle reads its real state: GET url, JSON field."""

    url: str
    field: str


@dataclass(frozen=True)
class Key:
    slot: str
    title: str | None = None
    icon: str | None = None
    widget: str | None = None
    action: Action | None = None
    gestures: dict[str, Action] = field(default_factory=dict)
    toggle: tuple[ToggleState, ...] = ()
    toggle_initial: int = 0
    toggle_status: Status | None = None  # set: the key shows the polled state and a press sends the other
    health_url: str | None = None  # widget "health-json": the health.json to read (GET only)
    alerts: bool = False  # draw a border in the worst current alert's colour (as the screen saver)


@dataclass(frozen=True)
class Screen:
    name: str
    kind: Literal["page", "folder"]
    parent: str | None
    keys: dict[str, Key]


@dataclass(frozen=True)
class Device:
    brightness: int = 80
    clock_minutes: int = 30  # screen saver: a large clock after this many idle minutes (0: never)
    sleep_minutes: int = 120  # keys off after this many idle minutes (0: never)


@dataclass(frozen=True)
class Gestures:
    double_ms: int = 300
    hold_ms: int = 500


@dataclass(frozen=True)
class Watchdog:
    interval_s: int = 10
    health_timeout_s: int = 2
    uhubctl: bool = False
    uhubctl_location: str = ""


@dataclass(frozen=True)
class AutoBrightnessConfig:
    """Brightness from a room-light reading: (light, percent) points, linear between them."""

    url: str
    points: tuple[tuple[float, int], ...]


@dataclass(frozen=True)
class Config:
    pages: tuple[str, ...]
    screens: dict[str, Screen]
    device: Device = Device()
    gestures: Gestures = Gestures()
    watchdog: Watchdog = Watchdog()
    pihole_service: str = "hexclack-pihole"
    auto_brightness: AutoBrightnessConfig | None = None
    stations: dict[str, str] = field(default_factory=dict)  # [music.stations]: alias -> Apple Music URL


def load(path: Path = DEFAULT_PATH) -> Config:
    """Read and validate a config file. Raises ConfigError on any problem."""
    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError as err:
        raise ConfigError(f"{path}: file not found") from err
    except tomllib.TOMLDecodeError as err:
        raise ConfigError(f"{path}: invalid TOML: {err}") from err
    return parse(raw)


def parse(raw: dict[str, Any]) -> Config:
    """Validate an already-parsed TOML document."""
    _no_unknown(raw, TOP_LEVEL, "top level")
    stations = _stations(raw)
    screens_raw = _table(raw.get("screens"), "screens")
    if not screens_raw:
        raise ConfigError("screens: at least one screen is required")
    screens = {name: _screen(name, _table(body, f"screens.{name}"), stations) for name, body in screens_raw.items()}

    pages = raw.get("pages")
    if not isinstance(pages, list) or not pages or not all(isinstance(p, str) for p in pages):
        raise ConfigError("pages: must be a non-empty list of screen names")
    page_names = {n for n, s in screens.items() if s.kind == "page"}
    for p in pages:
        if p not in screens:
            raise ConfigError(f"pages: unknown screen {p!r}")
        if screens[p].kind != "page":
            raise ConfigError(f"pages: {p!r} is a folder, not a page")
    if missing := page_names - set(pages):
        raise ConfigError(f"pages: page screens missing from the order: {sorted(missing)}")
    if len(set(pages)) != len(pages):
        raise ConfigError("pages: a screen is listed twice")

    for screen in screens.values():
        if screen.kind == "folder" and screen.parent not in screens:
            raise ConfigError(f"screens.{screen.name}: parent {screen.parent!r} does not exist")
        for key in screen.keys.values():
            for action in _actions_of(key):
                if action.kind == "nav" and "folder" in action.fields:
                    target = action.fields["folder"]
                    if target not in screens or screens[target].kind != "folder":
                        raise ConfigError(f"{_where(screen.name, key.slot)}: nav folder {target!r} is not a folder")

    device = _section(raw, "device", Device)
    if device.clock_minutes < 0 or device.sleep_minutes < 0:
        raise ConfigError("device: clock_minutes and sleep_minutes must be 0 (off) or more")
    if device.clock_minutes and device.sleep_minutes and device.clock_minutes >= device.sleep_minutes:
        raise ConfigError("device: clock_minutes must be less than sleep_minutes (the clock comes before off)")
    return Config(
        pages=tuple(pages),
        screens=screens,
        device=device,
        gestures=_section(raw, "gestures", Gestures),
        watchdog=_section(raw, "watchdog", Watchdog),
        pihole_service=_secrets(raw),
        auto_brightness=_auto_brightness(raw),
        stations=stations,
    )


def _stations(raw: dict[str, Any]) -> dict[str, str]:
    """[music.stations]: station alias -> full https://music.apple.com/... URL."""
    body = _table(raw.get("music", {}), "music")
    _no_unknown(body, {"stations"}, "music")
    stations = _table(body.get("stations", {}), "music.stations")
    for alias, url in stations.items():
        at = f"music.stations.{alias}"
        if not alias:
            raise ConfigError("music.stations: a station alias must not be empty")
        if not isinstance(url, str):
            raise ConfigError(f"{at}: must be a string URL")
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != STATION_HOST or parts.path.strip("/") == "":
            raise ConfigError(f"{at}: must be a full https://{STATION_HOST}/... URL, got {url!r}")
    return dict(stations)


def _screen(name: str, body: dict[str, Any], stations: dict[str, str]) -> Screen:
    where = f"screens.{name}"
    _no_unknown(body, {"kind", "parent", "keys"}, where)
    kind = body.get("kind")
    if kind not in ("page", "folder"):
        raise ConfigError(f"{where}: kind must be 'page' or 'folder', got {kind!r}")
    parent = body.get("parent")
    if kind == "folder" and not isinstance(parent, str):
        raise ConfigError(f"{where}: a folder needs a parent screen")
    if kind == "page" and parent is not None:
        raise ConfigError(f"{where}: a page has no parent")
    keys: dict[str, Key] = {}
    for slot, key_body in _table(body.get("keys", {}), f"{where}.keys").items():
        _slot(name, slot)
        if kind == "folder" and slot == BACK_SLOT:
            raise ConfigError(f"{_where(name, slot)}: 0,0 is the automatic back key in a folder")
        keys[slot] = _key(name, slot, _table(key_body, _where(name, slot)), stations)
    return Screen(name=name, kind=kind, parent=parent if kind == "folder" else None, keys=keys)


def _slot(screen: str, slot: str) -> None:
    parts = slot.split(",")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ConfigError(f"{_where(screen, slot)}: slot must be 'col,row'")
    col, row = int(parts[0]), int(parts[1])
    if not (0 <= col < COLS and 0 <= row < ROWS):
        raise ConfigError(f"{_where(screen, slot)}: slot out of range (col 0-{COLS - 1}, row 0-{ROWS - 1})")


def _key(screen: str, slot: str, body: dict[str, Any], stations: dict[str, str]) -> Key:
    where = _where(screen, slot)
    _no_unknown(body, KEY_FIELDS, where)
    title = _opt_str(body, "title", where)
    icon = _opt_str(body, "icon", where)
    widget = _opt_str(body, "widget", where)
    if widget is not None and widget not in WIDGETS:
        raise ConfigError(f"{where}: widget must be one of {', '.join(WIDGETS)}, got {widget!r}")
    alerts = body.get("alerts", False)
    if not isinstance(alerts, bool):
        raise ConfigError(f"{where}: alerts must be true or false")
    health_url = None
    if "health" in body:
        health = _table(body["health"], f"{where}.health")
        _no_unknown(health, {"url"}, f"{where}.health")
        health_url = health.get("url")
        if not isinstance(health_url, str) or not health_url.startswith(("http://", "https://")):
            raise ConfigError(f"{where}: health.url must be an http(s) URL")
    if (widget in URL_WIDGETS) != (health_url is not None):
        raise ConfigError(f"{where}: widgets {', '.join(URL_WIDGETS)} need a health = {{ url }} table, others none")

    action_kinds = [k for k in ACTION_TYPES if k in body]
    gesture_kinds = [g for g in GESTURES if g in body]
    has_toggle = "toggle" in body
    used = len(action_kinds) + (1 if gesture_kinds else 0) + (1 if has_toggle else 0)
    if len(action_kinds) > 1:
        raise ConfigError(f"{where}: more than one action type: {', '.join(action_kinds)}")
    if used > 1:
        raise ConfigError(f"{where}: use one of a key-level action, gesture sub-tables or a toggle, not several")
    if "double" in body and "tap" not in body:
        raise ConfigError(f"{where}: a double gesture needs a tap gesture too")

    action = _action(body, action_kinds[0], where, stations) if action_kinds else None
    gestures = {g: _single_action(_table(body[g], f"{where}.{g}"), f"{where}.{g}", stations) for g in gesture_kinds}
    toggle: tuple[ToggleState, ...] = ()
    initial = 0
    status: Status | None = None
    if has_toggle:
        toggle, initial, status = _toggle(_table(body["toggle"], f"{where}.toggle"), f"{where}.toggle", stations)
    return Key(
        slot=slot,
        title=title,
        icon=icon,
        widget=widget,
        action=action,
        gestures=gestures,
        toggle=toggle,
        toggle_initial=initial,
        toggle_status=status,
        health_url=health_url,
        alerts=alerts,
    )


def _single_action(
    body: dict[str, Any], where: str, stations: dict[str, str], extra: frozenset[str] = frozenset()
) -> Action:
    """A table that must hold exactly one action type (a gesture sub-table or a toggle state)."""
    _no_unknown(body, set(ACTION_TYPES) | extra, where)
    kinds = [k for k in ACTION_TYPES if k in body]
    if len(kinds) != 1:
        raise ConfigError(f"{where}: needs exactly one action type, got {len(kinds)}")
    return _action(body, kinds[0], where, stations)


def _action(body: dict[str, Any], kind: str, where: str, stations: dict[str, str]) -> Action:
    fields = _table(body[kind], f"{where}.{kind}")
    at = f"{where}: {kind}"
    if kind == "music":
        return Action(kind=kind, fields=_music(fields, at, stations))
    if kind == "nav":
        _nav(fields, at)
    else:
        spec = ACTION_FIELDS[kind]
        _no_unknown(fields, set(spec), at)
        for name, required in spec.items():
            if required and name not in fields:
                raise ConfigError(f"{at} needs {name!r}")
        if kind == "http" and fields["method"] not in HTTP_METHODS:
            raise ConfigError(f"{at} method must be one of {', '.join(HTTP_METHODS)}")
        if kind == "pihole" and (
            not isinstance(fields["disable_seconds"], int) or isinstance(fields["disable_seconds"], bool)
        ):
            raise ConfigError(f"{at} disable_seconds must be an integer")
        for name, value in fields.items():
            if name != "disable_seconds" and not isinstance(value, str):
                raise ConfigError(f"{at} {name!r} must be a string")
    return Action(kind=kind, fields=dict(fields))


def _music(fields: dict[str, Any], at: str, stations: dict[str, str]) -> dict[str, Any]:
    """Validate a music action. A station's alias is resolved here: the returned fields carry its "url"."""
    action = fields.get("action")
    if action not in MUSIC_ACTIONS:
        raise ConfigError(f"{at} action must be one of {', '.join(MUSIC_ACTIONS)}, got {action!r}")
    needed = MUSIC_FIELDS.get(action, ())
    _no_unknown(fields, {"action", *needed}, at)
    for name in needed:
        if not isinstance(fields.get(name), str):
            raise ConfigError(f"{at} {action} needs a string {name!r}")
    if action == "bot" and fields["mode"] not in BOT_MODES:
        raise ConfigError(f"{at} bot mode must be 'latest' or 'shuffle'")
    if action == "station":
        url = stations.get(fields["name"])
        if url is None:
            known = ", ".join(stations) or "none (add [music.stations])"
            raise ConfigError(f"{at} unknown station {fields['name']!r}; known: {known}")
        return {**fields, "url": url}
    return dict(fields)


def _nav(fields: dict[str, Any], at: str) -> None:
    _no_unknown(fields, {"page", "folder", "home"}, at)
    if len(fields) != 1:
        raise ConfigError(f"{at} needs exactly one of 'page', 'folder' or 'home'")
    if "home" in fields and fields["home"] is not True:
        raise ConfigError(f"{at} home must be true")
    if "page" in fields and fields["page"] not in ("prev", "next"):
        raise ConfigError(f"{at} page must be 'prev' or 'next'")
    if "folder" in fields and not isinstance(fields["folder"], str):
        raise ConfigError(f"{at} folder must be a screen name")


def _toggle(
    body: dict[str, Any], where: str, stations: dict[str, str]
) -> tuple[tuple[ToggleState, ...], int, Status | None]:
    _no_unknown(body, {"states", "initial", "status"}, where)
    status = _status(body["status"], f"{where}.status") if "status" in body else None
    states_raw = body.get("states")
    if not isinstance(states_raw, list) or len(states_raw) < 2:
        raise ConfigError(f"{where}: states must be a list of at least 2 tables")
    states = []
    for i, raw in enumerate(states_raw):
        at = f"{where}.states[{i}]"
        state = _table(raw, at)
        label = state.get("label")
        if not isinstance(label, str):
            raise ConfigError(f"{at}: needs a string 'label'")
        action = _single_action(state, at, stations, frozenset({"label", "icon", "value"}))
        if status is not None and "value" not in state:
            raise ConfigError(f"{at}: a toggle with a status source needs a 'value' on every state")
        if status is None and "value" in state:
            raise ConfigError(f"{at}: 'value' only applies to a toggle with a status source")
        states.append(
            ToggleState(label=label, icon=_opt_str(state, "icon", at), action=action, value=state.get("value"))
        )
    if status is not None and len({repr(s.value) for s in states}) != len(states):
        raise ConfigError(f"{where}: state values must be distinct")
    if status is not None and "initial" in body:
        raise ConfigError(f"{where}: initial does not apply to a toggle with a status source (the status decides)")
    initial = body.get("initial", 0)
    if not isinstance(initial, int) or isinstance(initial, bool) or not 0 <= initial < len(states):
        raise ConfigError(f"{where}: initial must be a state index from 0 to {len(states) - 1}")
    return tuple(states), initial, status


def _status(raw: object, where: str) -> Status:
    body = _table(raw, where)
    _no_unknown(body, {"url", "field"}, where)
    url, field_name = body.get("url"), body.get("field")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ConfigError(f"{where}: url must be an http(s) URL")
    if not isinstance(field_name, str) or not field_name:
        raise ConfigError(f"{where}: field must name a key in the JSON reply")
    return Status(url=url, field=field_name)


def _section[T](raw: dict[str, Any], name: str, cls: type[T]) -> T:
    body = _table(raw.get(name, {}), name)
    defaults = cls()
    allowed = set(vars(defaults))
    _no_unknown(body, allowed, name)
    for key, value in body.items():
        expected = type(getattr(defaults, key))
        if type(value) is not expected:
            raise ConfigError(f"{name}.{key}: must be {expected.__name__}, got {type(value).__name__}")
    return cls(**body)


def _auto_brightness(raw: dict[str, Any]) -> AutoBrightnessConfig | None:
    if "auto_brightness" not in raw:
        return None
    where = "auto_brightness"
    body = _table(raw["auto_brightness"], where)
    _no_unknown(body, {"url", "points"}, where)
    url = body.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ConfigError(f"{where}.url: must be an http(s) URL")
    raw_points = body.get("points")
    if not isinstance(raw_points, list) or len(raw_points) < 2:
        raise ConfigError(f"{where}.points: at least two [light, percent] pairs")
    points: list[tuple[float, int]] = []
    for p in raw_points:
        ok = isinstance(p, list) and len(p) == 2 and isinstance(p[0], int | float) and isinstance(p[1], int)
        if not ok or not 0 <= p[1] <= 100:
            raise ConfigError(f"{where}.points: each point is [light, percent 0-100], got {p!r}")
        points.append((float(p[0]), int(p[1])))
    if any(b[0] <= a[0] for a, b in pairwise(points)):
        raise ConfigError(f"{where}.points: light values must increase")
    return AutoBrightnessConfig(url=url, points=tuple(points))


def _secrets(raw: dict[str, Any]) -> str:
    body = _table(raw.get("secrets", {}), "secrets")
    _no_unknown(body, {"pihole_service"}, "secrets")
    service = body.get("pihole_service", "hexclack-pihole")
    if not isinstance(service, str):
        raise ConfigError("secrets.pihole_service: must be a string")
    return service


def _actions_of(key: Key) -> list[Action]:
    actions = [key.action] if key.action else []
    actions += key.gestures.values()
    actions += [s.action for s in key.toggle]
    return actions


def _table(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: must be a table")
    return value


def _opt_str(body: dict[str, Any], name: str, where: str) -> str | None:
    value = body.get(name)
    if value is not None and not isinstance(value, str):
        raise ConfigError(f"{where}: {name!r} must be a string")
    return value


def _no_unknown(body: dict[str, Any], allowed: set[str] | frozenset[str], where: str) -> None:
    if unknown := sorted(set(body) - set(allowed)):
        raise ConfigError(f"{where}: unknown field(s): {', '.join(unknown)}")


def _where(screen: str, slot: str) -> str:
    return f'screens.{screen}.keys."{slot}"'
