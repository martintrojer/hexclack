"""Draw keys and screens (docs/design.md section 6).

Key images are 80x80 RGB. Icon paths in the config are relative to the config file's directory.
`to_device` converts an image for the Mini; `hexclack render` never calls it, so screens can be
drawn without a device.
"""

import io
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from hexclack import tiles
from hexclack.config import BACK_SLOT, COLS, ROWS, Config, Key, Screen

if TYPE_CHECKING:
    from StreamDeck.Devices.StreamDeck import StreamDeck

KEY_SIZE = 80
PRE_ARROWED = "icons/nav/"  # the Home nav pictures already carry their arrow
GAP = 0


def icon_image(path: Path, size: int = KEY_SIZE) -> Image.Image:
    """An icon file scaled to size x size, flattened onto black."""
    with Image.open(path) as source:
        image = source.convert("RGBA")
    image = image.resize((size, size), Image.Resampling.LANCZOS)
    background = Image.new("RGBA", (size, size), "black")
    background.alpha_composite(image)
    return background.convert("RGB")


TITLE_BAND_ALPHA = 96  # black veil over the icon; lower = more of the artwork shows through


def title_band_height(title: str, size: int = KEY_SIZE) -> int:
    """Pixel height of the translucent title band overlay_title would draw."""
    measure = ImageDraw.Draw(Image.new("RGBA", (size, size)))
    font, lines = tiles.fit_text(measure, title, size - 6, max(10, size // 6), max(8, size // 10), step=1)
    return round(font.size * 1.15) * len(lines) + 4


def overlay_title(image: Image.Image, title: str) -> Image.Image:
    """Draw title in white on a translucent dark band along the bottom of image."""
    base = image.convert("RGBA")
    size = base.width
    measure = ImageDraw.Draw(Image.new("RGBA", (size, size)))
    font, lines = tiles.fit_text(measure, title, size - 6, max(10, size // 6), max(8, size // 10), step=1)
    line_height = round(font.size * 1.15)
    band = line_height * len(lines) + 4
    veil = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(veil).rectangle((0, size - band, size, size), fill=(0, 0, 0, TITLE_BAND_ALPHA))
    out = Image.alpha_composite(base, veil)
    draw = ImageDraw.Draw(out)
    for i, line in enumerate(lines):
        y = size - band + 2 + i * line_height + line_height // 2
        draw.text((size // 2, y), line, font=font, fill="white", anchor="mm")
    return out.convert("RGB")


def home_key(size: int = KEY_SIZE) -> Image.Image:
    """The one Home key: every folder's 0,0 and every nav-home key (glyph + title overlay)."""
    return tiles.cached(
        {"kind": "home", "title": "Home"},
        size,
        lambda: overlay_title(tiles.render_home_key(size), "Home"),
    )


def placeholder(label: str, size: int = KEY_SIZE) -> Image.Image:
    """A grey tile for widget keys until their widget draws (P5)."""
    image = Image.new("RGB", (size, size), (40, 40, 40))
    font = ImageFont.truetype(tiles.TEXT_FONT, max(8, size // 8), index=tiles.BOLD_INDEX)
    ImageDraw.Draw(image).text((size // 2, size // 2), label, font=font, fill=(180, 180, 180), anchor="mm")
    return image


def key_image(key: Key, base: Path, size: int = KEY_SIZE, *, folder_chevron: bool = True) -> Image.Image:
    """The static image of one configured key.

    folder_chevron: when True (default), every nav-folder key gets an edge arrow, on pages
    and folders alike. Pass False only for tests that want the bare face. Icons under
    PRE_ARROWED already carry their arrow and are left alone.
    """
    icon = key.icon
    if key.toggle:
        state = key.toggle[key.toggle_initial]
        icon = state.icon or icon
        # Prefer the key title overlay; fall back to state label only when there is no icon.
        title = key.title or (state.label if not state.icon else None)
    else:
        title = key.title
    if key.tile is not None:
        tile = key.tile
        image = tiles.cached(
            {"kind": "key_tile", "glyph": tile.glyph, "start": tile.start, "end": tile.end},
            size,
            lambda: tiles.render_tile(
                tiles.Tile("", tile.glyph, tile.start, tile.end, caption=False),
                size,
            ),
        )
        image = overlay_title(image, title) if title else image
        if folder_chevron and needs_chevron(key):
            # Lift a down chevron above the title band (Bot / Mellow clash otherwise).
            lift = title_band_height(title, size) if title and arrow_for(key.slot) == "down" else 0
            image = tiles.add_chevron(image, arrow_for(key.slot), lift=lift)
        return image
    if icon:
        image = icon_image(base / icon, size)
        image = overlay_title(image, title) if title else image
        if folder_chevron and needs_chevron(key) and not icon.startswith(PRE_ARROWED):
            lift = title_band_height(title, size) if title and arrow_for(key.slot) == "down" else 0
            image = tiles.add_chevron(image, arrow_for(key.slot), lift=lift)
        return image
    if key.action is not None and key.action.kind == "nav" and key.action.fields.get("home"):
        return home_key(size)  # same image as every folder's 0,0
    if (
        key.action is not None
        and key.action.kind == "nav"
        and (key.action.fields.get("ephemeral_next") or key.action.fields.get("bot_list_next"))
    ):
        label = title or "Next"
        return tiles.cached(
            {"kind": "ephemeral_next", "title": label},
            size,
            lambda: overlay_title(tiles.render_nav("right", size=size), label),
        )
    if key.widget:
        return placeholder(key.widget, size)
    if title:
        return tiles.cached({"kind": "title", "title": title}, size, lambda: tiles.title_tile(title, size))
    return Image.new("RGB", (size, size), "black")


def arrow_for(slot: str) -> str:
    """The arrow points at the key's own outer edge (user rule): top row left, up, right; bottom row
    left, down, right."""
    col, row = (int(p) for p in slot.split(","))
    if col == 0:
        return "left"
    if col == COLS - 1:
        return "right"
    return "up" if row == 0 else "down"


def opens_folder(key: Key) -> bool:
    return key.action is not None and key.action.kind == "nav" and "folder" in key.action.fields


def opens_ephemeral_list(key: Key) -> bool:
    """Mine/Curated explore and Favourites — drill into an ephemeral list, same as a folder."""
    if key.action is None or key.action.kind != "music":
        return False
    return key.action.fields.get("action") in {"explore", "favourites"}


def needs_chevron(key: Key) -> bool:
    """Edge arrow for any key that navigates into another screen or ephemeral list."""
    return opens_folder(key) or opens_ephemeral_list(key)


def screen_images(screen: Screen, base: Path, size: int = KEY_SIZE) -> dict[str, Image.Image]:
    """Every slot of screen, blank slots included, keyed by 'col,row'."""
    images: dict[str, Image.Image] = {}
    for row in range(ROWS):
        for col in range(COLS):
            slot = f"{col},{row}"
            if screen.kind == "folder" and slot == BACK_SLOT:
                images[slot] = home_key(size)
            elif slot in screen.keys:
                images[slot] = key_image(screen.keys[slot], base, size)
            else:
                images[slot] = Image.new("RGB", (size, size), "black")
    return images


def screen_grid(screen: Screen, base: Path, size: int = KEY_SIZE) -> Image.Image:
    """The screen as one COLS x ROWS image, as the deck shows it."""
    grid = Image.new("RGB", (COLS * size + (COLS - 1) * GAP, ROWS * size + (ROWS - 1) * GAP), "black")
    for slot, image in screen_images(screen, base, size).items():
        col, row = (int(p) for p in slot.split(","))
        grid.paste(image, (col * (size + GAP), row * (size + GAP)))
    return grid


def render_screens(cfg: Config, base: Path, out: Path, names: list[str]) -> list[Path]:
    """Write <name>.png grids to out. Returns the written paths."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name in names:
        path = out / f"{name}.png"
        screen_grid(cfg.screens[name], base).save(path)
        written.append(path)
    return written


# Catppuccin Mocha accent colours, in palette order (the Catppuccin palette). The screen
# saver clock steps through them, one per redraw (once a minute): no extra redraws for colour.
MOCHA_ACCENTS: tuple[str, ...] = (
    "#f5e0dc",  # rosewater
    "#f2cdcd",  # flamingo
    "#f5c2e7",  # pink
    "#cba6f7",  # mauve
    "#f38ba8",  # red
    "#eba0ac",  # maroon
    "#fab387",  # peach
    "#f9e2af",  # yellow
    "#a6e3a1",  # green
    "#94e2d5",  # teal
    "#89dceb",  # sky
    "#74c7ec",  # sapphire
    "#89b4fa",  # blue
    "#b4befe",  # lavender
)
MOCHA_BASE = "#1e1e2e"


# The clock cycle: seven clearly distinct accents, ordered warm/cool so every step moves at least
# ~126 degrees of hue. Palette order stepped through near-neighbours (rosewater -> flamingo is 10
# degrees, red -> maroon 7), so half the minute changes were invisible (user report).
CLOCK_CYCLE: tuple[str, ...] = (
    "#f38ba8",  # red
    "#a6e3a1",  # green
    "#cba6f7",  # mauve
    "#f9e2af",  # yellow
    "#89dceb",  # sky
    "#fab387",  # peach
    "#89b4fa",  # blue
)


def clock_colour(minute_of_day: int) -> str:
    """The accent for a given minute: a clearly different colour each minute."""
    return CLOCK_CYCLE[minute_of_day % len(CLOCK_CYCLE)]


ALERT_COLOURS = {1: (255, 130, 20), 2: (235, 40, 50)}  # alerts.Severity: WARN orange, BAD red (as the AQ scale)


def clock_keys(
    now_text: str,
    size: int = KEY_SIZE,
    fill: float = 0.94,
    colour: str = "white",
    alerts: list[tuple[str, int]] | None = None,
    background: bytes | None = None,
) -> dict[int, Image.Image]:
    """The screen saver: one HH:MM spanning the whole 3x2 deck, cut into key images.

    Bold digits are about three times wider than the deck is tall relative to its width, so the text
    is drawn at its natural size, cropped to its ink, and stretched to fill `fill` of the deck in
    both directions: tall, condensed digits (user request: span all the area).
    """
    width, height = COLS * size, ROWS * size
    stripe = _alert_stripe(alerts or [], width, size) if alerts else None
    digits_h = height - (stripe.height if stripe else 0)
    art = _clock_background(background, width, height) if background else None
    font = (tiles.light if art else tiles.bold)(height * 2)  # thin digits over art (user request)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), now_text, font=font)
    ink = Image.new("L", (round(right - left), round(bottom - top)), 0)
    ImageDraw.Draw(ink).text((-left, -top), now_text, font=font, fill=255)
    target = (round(width * fill), round(digits_h * fill))
    ink = ink.resize(target, Image.Resampling.LANCZOS)
    canvas = art or Image.new("RGB", (width, height), "black")
    at = ((width - target[0]) // 2, (digits_h - target[1]) // 2)
    if art:  # a dark outline keeps the digits readable over bright covers
        canvas.paste("black", at, ink.filter(ImageFilter.MaxFilter(5)))
    canvas.paste(colour, at, ink)
    if stripe is not None:
        canvas.paste(stripe, (0, height - stripe.height))
    return {
        row * COLS + col: canvas.crop((col * size, row * size, (col + 1) * size, (row + 1) * size))
        for row in range(ROWS)
        for col in range(COLS)
    }


CLOCK_ART_BRIGHTNESS = 0.4  # dim enough that the digits stay readable over any cover
CLOCK_ART_ZOOM = 0.5  # 0 = whole cover with black bars, 1 = fill the deck, cropping (user request: zoom less)


def _clock_background(data: bytes, width: int, height: int) -> Image.Image | None:
    """Album art scaled between fit and fill (CLOCK_ART_ZOOM), centred on black and dimmed, not
    blurred (user request: sharp art reads better). A square cover on the 3:2 deck loses a little top
    and bottom and gets narrow side bars.
    None for unreadable data: the caller draws the plain clock."""
    try:
        with Image.open(io.BytesIO(data)) as source:
            art = source.convert("RGB")
    except (OSError, ValueError):
        return None
    fit, fill = min(width / art.width, height / art.height), max(width / art.width, height / art.height)
    scale = fit + (fill - fit) * CLOCK_ART_ZOOM
    art = art.resize((max(1, round(art.width * scale)), max(1, round(art.height * scale))), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), "black")
    canvas.paste(art, ((width - art.width) // 2, (height - art.height) // 2))  # overhang is cropped
    return ImageEnhance.Brightness(canvas).enhance(CLOCK_ART_BRIGHTNESS)


def _alert_stripe(alerts: list[tuple[str, int]], width: int, size: int) -> Image.Image:
    """A band of equal segments along the bottom of the deck, one per alert: severity colour,
    label in black. Shown only while something needs attention."""
    band_h = round(size * 0.42)
    band = Image.new("RGB", (width, band_h), "black")
    draw = ImageDraw.Draw(band)
    shown = alerts[:COLS]  # at most one segment per column of keys
    seg_w = width / len(shown)
    for i, (label, severity) in enumerate(shown):
        x0, x1 = round(i * seg_w) + 2, round((i + 1) * seg_w) - 2
        draw.rounded_rectangle((x0, 3, x1, band_h - 1), radius=6, fill=ALERT_COLOURS.get(severity, (166, 173, 200)))
        font, lines = tiles.fit_text(draw, label, x1 - x0 - 6, round(band_h * 0.55), 8, step=1)
        line_h = round(font.size * 1.1)
        top = (band_h + 3 - line_h * len(lines)) / 2 + line_h / 2
        for j, line in enumerate(lines):
            draw.text(((x0 + x1) / 2, top + j * line_h), line, font=font, fill="black", anchor="mm")
    return band


def alert_border(image: Image.Image, severity: int) -> Image.Image:
    """The key with a border in the screen saver's colour for this severity (0: unchanged)."""
    if severity not in ALERT_COLOURS:
        return image
    out = image.copy()
    width = max(3, out.width // 14)
    ImageDraw.Draw(out).rectangle((0, 0, out.width - 1, out.height - 1), outline=ALERT_COLOURS[severity], width=width)
    return out


def to_device(deck: "StreamDeck", image: Image.Image) -> bytes:
    """Convert an 80x80 image to the deck's native format (BMP, rotated and flipped)."""
    from StreamDeck.ImageHelpers import PILHelper  # imported lazily: needs hidapi only at run time

    return PILHelper.to_native_key_format(deck, image)
