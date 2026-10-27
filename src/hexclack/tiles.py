"""Generated key tiles (docs/music.md section 7).

Every drawing function takes a size; proportions were tuned at 288 px and are scaled from there.
Apple Color Emoji only renders at its bitmap sizes, so glyphs are drawn at 160 and scaled. Results
are cached on disk keyed by the tile spec, size and TILE_VERSION; tiles are built once at startup
and never per key press.
"""

import colorsys
import hashlib
import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TILE_VERSION = 8  # bump when drawing code changes so cached tiles are rebuilt
PICK_FALLBACK_BG = (28, 28, 28)
BASE = 288  # the size the proportions were designed at
TEXT_FONT = "/System/Library/Fonts/HelveticaNeue.ttc"
BOLD_INDEX = 1
LIGHT_INDEX = 7
EMOJI_FONT = "/System/Library/Fonts/Apple Color Emoji.ttc"
EMOJI_SIZE = 160  # the largest bitmap size Apple Color Emoji renders at
CACHE = Path.home() / "Library/Caches/hexclack/tiles"


@dataclass(frozen=True)
class Tile:
    """A gradient tile with an emoji glyph and optional name caption.

    caption=False draws emoji only (centred); use a key `title` for the label.
    """

    name: str
    glyph: str
    start: str
    end: str
    mode: str = ""
    caption: bool = True


def _px(value: int, size: int) -> int:
    return max(1, round(value * size / BASE))


def hex_rgb(colour: str) -> tuple[int, int, int]:
    value = int(colour.lstrip("#"), 16)
    return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF


def gradient(start: str, end: str, size: int) -> Image.Image:
    """A square fading diagonally from start to end."""
    a, b = hex_rgb(start), hex_rgb(end)
    image = Image.new("RGBA", (size, size))
    pixels = image.load()
    assert pixels is not None
    span = 2 * (size - 1) or 1
    for y in range(size):
        for x in range(size):
            t = (x + y) / span
            r, g, bl = (round(a[i] + (b[i] - a[i]) * t) for i in range(3))
            pixels[x, y] = (r, g, bl, 255)
    return image


def glyph(emoji: str, size: int) -> Image.Image:
    """One colour emoji, cropped to its pixels and scaled so its longer side is size."""
    font = ImageFont.truetype(EMOJI_FONT, EMOJI_SIZE)
    canvas = Image.new("RGBA", (EMOJI_SIZE * 2, EMOJI_SIZE * 2))
    ImageDraw.Draw(canvas).text((EMOJI_SIZE // 2, EMOJI_SIZE // 2), emoji, font=font, embedded_color=True)
    box = canvas.getbbox()
    if box is None:
        raise ValueError(f"emoji {emoji!r} rendered nothing")
    image = canvas.crop(box)
    scale = size / max(image.size)
    return image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS
    )


def bold(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(TEXT_FONT, size, index=BOLD_INDEX)


def light(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(TEXT_FONT, size, index=LIGHT_INDEX)


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Greedy word wrap that keeps each line within width pixels."""
    lines: list[str] = []
    for word in text.split():
        if lines and draw.textlength(f"{lines[-1]} {word}", font=font) <= width:
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word)
    return lines


def fit_text(
    draw: ImageDraw.ImageDraw, text: str, width: int, largest: int, smallest: int, step: int = 2
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """The largest bold font from largest down to smallest that fits text in at most two lines."""
    for font_size in range(largest, smallest, -max(1, step)):
        font = bold(font_size)
        lines = wrap(draw, text, font, width)
        if len(lines) <= 2 and all(draw.textlength(line, font=font) <= width for line in lines):
            return font, lines
    font = bold(smallest)
    return font, wrap(draw, text, font, width)


def _ellipsis(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return (text.rstrip() + "…") if text else "…"


def fit_pick_name(
    draw: ImageDraw.ImageDraw, text: str, width: int, largest: int, smallest: int, step: int = 2
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Largest bold font that fits name in ≤2 lines; truncate with ellipsis rather than shrink further."""
    for font_size in range(largest, smallest - 1, -max(1, step)):
        font = bold(font_size)
        lines = wrap(draw, text, font, width)
        if len(lines) <= 2 and all(draw.textlength(line, font=font) <= width for line in lines):
            return font, lines
    font = bold(smallest)
    lines = wrap(draw, text, font, width)
    if not lines:
        return font, [""]
    if len(lines) == 1:
        return font, [_ellipsis(draw, lines[0], font, width)]
    # Cap at two lines; ellipsis any overflow (including a single overlong word).
    second = lines[1] if len(lines) == 2 else " ".join(lines[1:])
    return font, [_ellipsis(draw, lines[0], font, width), _ellipsis(draw, second, font, width)]


def shuffled_colors(
    keys: list[str] | tuple[str, ...],
    *,
    rng: random.Random | None = None,
    light: float = 0.24,
    sat: float = 0.72,
) -> dict[str, tuple[int, int, int]]:
    """Evenly spaced hues, shuffled once a list is known (Mine/Curated categories, Bot drops).

    Call when query results arrive so neighbours are not stuck on similar colours;
    store the mapping on the session so paging stays consistent for that open.
    """
    names = list(dict.fromkeys(k for k in keys if k))
    n = len(names)
    if n == 0:
        return {}
    slots = list(range(n))
    (rng or random.Random()).shuffle(slots)
    out: dict[str, tuple[int, int, int]] = {}
    for name, slot in zip(names, slots, strict=True):
        r, g, b = colorsys.hls_to_rgb(slot / n, light, sat)
        out[name] = (round(r * 255), round(g * 255), round(b * 255))
    return out


def render_tile(tile: Tile, size: int = 80) -> Image.Image:
    """Glyph top-right (or centred if no caption), optional mode top-left, name bottom-left."""
    margin = _px(24, size)
    image = gradient(tile.start, tile.end, size)
    if not tile.caption:
        mark = glyph(tile.glyph, _px(140, size))
        image.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
        return image.convert("RGB")
    mark = glyph(tile.glyph, _px(120, size))
    image.alpha_composite(mark, (size - margin - mark.width, margin))
    draw = ImageDraw.Draw(image)
    if tile.mode:
        draw.text((margin, margin), tile.mode.upper(), font=bold(_px(34, size)), fill="white", anchor="lt")
    font, lines = fit_text(draw, tile.name, size - 2 * margin, _px(52, size), _px(18, size))
    line_height = round(font.size * 1.1)
    for i, line in enumerate(reversed(lines)):
        draw.text((margin, size - margin - i * line_height), line, font=font, fill="white", anchor="ls")
    return image.convert("RGB")


Box = tuple[float, float, float, float]  # left, top, right, bottom


def _skip_shape(draw: ImageDraw.ImageDraw, box: Box, fill: int, forward: bool = True) -> None:
    """Two triangles and a bar: Next when forward, Previous (mirrored) otherwise."""
    left, top, right, bottom = box
    width, mid = right - left, (top + bottom) / 2
    bar = width * 0.14
    tri = (width - bar) / 2
    sign, origin = (1, left) if forward else (-1, right)
    for offset in (0, tri):
        base = origin + sign * offset
        draw.polygon([(base, top), (base + sign * tri, mid), (base, bottom)], fill=fill)
    edge = origin + sign * (width - bar)
    draw.rectangle((min(edge, edge + sign * bar), top, max(edge, edge + sign * bar), bottom), fill=fill)


def _shuffle_shape(draw: ImageDraw.ImageDraw, box: Box, fill: int) -> None:
    """Two crossing arrows pointing right."""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    stroke = max(1, round(height * 0.14))
    head = height * 0.3
    tail = right - head
    low, high = top + head, bottom - head
    for start_y, end_y in ((high, low), (low, high)):
        path = [(left, start_y), (left + width * 0.22, start_y), (tail - width * 0.15, end_y), (tail, end_y)]
        draw.line(path, fill=fill, width=stroke, joint="curve")
        draw.polygon([(tail, end_y - head), (right, end_y), (tail, end_y + head)], fill=fill)


def render_skip(size: int = 80) -> Image.Image:
    """Track skip key: a large white Next mark, smaller grey Previous and Shuffle marks along the bottom.

    Drawn as a greyscale mask at 4x and downsampled so edges are antialiased at key size.
    """
    scale = 4
    big = size * scale
    mask = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(mask)

    def px(value: int) -> int:
        return _px(value, size) * scale

    side = px(150)
    left, top = (big - side) / 2, px(36)
    _skip_shape(draw, (left, top, left + side, top + side * 0.6), 255)

    small, gap, bottom = px(64), px(40), big - px(24)
    height = small * 0.6
    x = (big - 2 * small - gap) / 2
    _skip_shape(draw, (x, bottom - height, x + small, bottom), 140, forward=False)
    x += small + gap
    _shuffle_shape(draw, (x, bottom - height, x + small, bottom), 140)
    return mask.resize((size, size), Image.Resampling.LANCZOS).convert("RGB")


def title_tile(title: str, size: int = 80) -> Image.Image:
    """A black key with a centred title, for keys that have no icon."""
    image = Image.new("RGB", (size, size), "black")
    draw = ImageDraw.Draw(image)
    font, lines = fit_text(draw, title, size - 2 * _px(12, size), _px(64, size), _px(30, size))
    line_height = round(font.size * 1.15)
    top = (size - line_height * len(lines)) // 2 + line_height // 2
    for i, line in enumerate(lines):
        draw.text((size // 2, top + i * line_height), line, font=font, fill="white", anchor="mm")
    return image


def playlist_tile(
    extra: str | None,
    day: str,
    year: str,
    size: int = 80,
    bg: tuple[int, int, int] | None = None,
) -> Image.Image:
    """Bot list key: fixed rows for metadata / month-day / year so long names stay readable."""
    lines = [extra, day, year] if extra else [day, year]
    # Date/year dominate; metadata stays smaller so a long subtitle does not crowd them.
    fonts = (
        (bold(_px(40, size)), bold(_px(72, size)), bold(_px(56, size)))
        if extra
        else (bold(_px(84, size)), bold(_px(64, size)))
    )
    image = Image.new("RGB", (size, size), bg if bg is not None else PICK_FALLBACK_BG)
    draw = ImageDraw.Draw(image)
    heights = [round(font.size * 1.15) for font in fonts]
    top = (size - sum(heights)) // 2
    y = top
    for line, font, height in zip(lines, fonts, heights, strict=True):
        assert line is not None
        draw.text((size // 2, y + height // 2), line, font=font, fill="white", anchor="mm")
        y += height
    return image


def pick_tile(name: str, category: str, size: int = 80, bg: tuple[int, int, int] | None = None) -> Image.Image:
    """Curated/Mine key: playlist name (≤2 lines) over category; subtle category-tinted background."""
    image = Image.new("RGB", (size, size), bg if bg is not None else PICK_FALLBACK_BG)
    draw = ImageDraw.Draw(image)
    margin = _px(8, size)
    cat_font = light(_px(36, size))
    cat_height = round(cat_font.size * 1.15)
    width = size - 2 * margin
    # Prefer large type; truncate rather than shrinking into unreadability.
    name_font, name_lines = fit_pick_name(draw, name, width, _px(88, size), _px(52, size), step=2)
    line_height = round(name_font.size * 1.12)
    name_block = line_height * len(name_lines)
    total = name_block + cat_height
    top = max(margin, (size - total) // 2)
    y = top
    for line in name_lines:
        draw.text((size // 2, y + line_height // 2), line, font=name_font, fill="white", anchor="mm")
        y += line_height
    cat = _ellipsis(draw, category, cat_font, width)
    draw.text((size // 2, y + cat_height // 2), cat, font=cat_font, fill=(200, 200, 200), anchor="mm")
    return image


def cached(spec: dict[str, object], size: int, build: Callable[[], Image.Image], cache: Path = CACHE) -> Image.Image:
    """Return the tile for spec from the disk cache, building and storing it on a miss."""
    blob = json.dumps({"spec": spec, "size": size, "version": TILE_VERSION}, sort_keys=True)
    path = cache / f"{hashlib.sha256(blob.encode()).hexdigest()}.png"
    if path.exists():
        with Image.open(path) as image:
            return image.convert("RGB")
    image = build()
    cache.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    image.save(tmp, format="PNG")
    tmp.replace(path)
    return image


# Unit vector each chevron points along.
DIRECTIONS: dict[str, tuple[int, int]] = {"right": (1, 0), "left": (-1, 0), "up": (0, -1), "down": (0, 1)}


def _chevron(draw: ImageDraw.ImageDraw, tip: tuple[int, int], direction: str, arm: int, fill: str, width: int) -> None:
    dx, dy = DIRECTIONS[direction]
    back = (tip[0] - arm * dx, tip[1] - arm * dy)
    arms = [(back[0] - arm * dy, back[1] + arm * dx), (back[0] + arm * dy, back[1] - arm * dx)]
    draw.line([arms[0], tip, arms[1]], fill=fill, width=width, joint="curve")


def render_nav(direction: str = "right", emoji: str = "", size: int = 80) -> Image.Image:
    """A chevron in a white rounded square on black (label via overlay_title)."""
    image = Image.new("RGBA", (size, size), "black")
    draw = ImageDraw.Draw(image)
    side = round(size * 54 / 144)
    left, top = (size - side) // 2, (size - side) // 2
    draw.rounded_rectangle((left, top, left + side, top + side), radius=round(side / 8), fill="white")
    dx, dy = DIRECTIONS[direction]
    tip = (left + side // 2 + _px(6, size) * dx, top + side // 2 + _px(6, size) * dy)
    _chevron(draw, tip, direction, side // 4, "black", _px(10, size))
    if emoji:
        margin = _px(24, size)
        mark_side = _px(48, size)
        mark = glyph(emoji, _px(120, size)).resize((mark_side, mark_side), Image.Resampling.LANCZOS)
        image.alpha_composite(mark, (size - margin - mark.width, max(0, margin - _px(8, size))))
    return image.convert("RGB")


def add_chevron(image: Image.Image, direction: str, *, lift: int = 0) -> Image.Image:
    """Edge chevron on a key face. lift shifts a down tip up (clear of a title band)."""
    out = image.convert("RGB").copy()
    size = out.width
    dx, dy = DIRECTIONS[direction]
    inset = _px(22, size)
    tip = (size // 2 + dx * (size // 2 - inset), size // 2 + dy * (size // 2 - inset))
    if direction == "down" and lift > 0:
        tip = (tip[0], tip[1] - lift)
    draw = ImageDraw.Draw(out)
    _chevron(draw, tip, direction, _px(18, size), "black", _px(8, size) + 3)
    _chevron(draw, tip, direction, _px(18, size), "white", _px(8, size))
    return out


def render_home_nav(emoji: str, direction: str, size: int = 80) -> Image.Image:
    """A large picture with a small white chevron on the edge it leads to."""
    image = Image.new("RGBA", (size, size), "black")
    side = _px(176, size)
    mark = glyph(emoji, _px(120, size)).resize((side, side), Image.Resampling.LANCZOS)
    dx, dy = DIRECTIONS[direction]
    nudge = _px(14, size)
    image.alpha_composite(mark, ((size - mark.width) // 2 - nudge * dx, (size - mark.height) // 2 - nudge * dy))
    inset = _px(22, size)
    tip = (size // 2 + dx * (size // 2 - inset), size // 2 + dy * (size // 2 - inset))
    _chevron(ImageDraw.Draw(image), tip, direction, _px(18, size), "white", _px(8, size))
    return image.convert("RGB")


def render_home_key(size: int = 80) -> Image.Image:
    """A house in a white rounded square on black (label via overlay_title)."""
    image = Image.new("RGBA", (size, size), "black")
    draw = ImageDraw.Draw(image)
    side = round(size * 54 / 144)
    left, top = (size - side) // 2, (size - side) // 2
    draw.rounded_rectangle((left, top, left + side, top + side), radius=round(side / 8), fill="white")
    cx, s = left + side / 2, side
    roof = [(cx, top + s * 0.18), (left + s * 0.16, top + s * 0.5), (left + s * 0.84, top + s * 0.5)]
    draw.polygon(roof, fill="black")
    body = (left + s * 0.27, top + s * 0.48, left + s * 0.73, top + s * 0.82)
    draw.rectangle(body, fill="black")
    door = (cx - s * 0.08, top + s * 0.62, cx + s * 0.08, top + s * 0.82)
    draw.rectangle(door, fill="white")
    return image.convert("RGB")
