"""Bake the sample icon set under examples/icons/.

Not imported by the daemon. Key faces in a real install come from config
(`tile = { glyph, start, end }` or `icon = "..."`). This catalog only exists so
`examples/icons/` can be regenerated without shipping a personal layout in the
library package.

  uv run python examples/generate_icons.py [OUT_DIR]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

from hexclack.tiles import BASE, Tile, render_home_nav, render_skip, render_tile

BOT_MODES = ("Latest", "Shuffle")

# group -> tiles. Bot categories also get "<name> Latest" and "<name> Shuffle".
TILES: dict[str, list[tuple[Tile, tuple[str, ...]]]] = {
    # caption=False: names come from key title overlays at render time.
    "bot": [
        (Tile("Bot", "🤖", "#3a3a3c", "#0b0b0c", caption=False), ()),
        (Tile("Beats", "🤖", "#ff2d55", "#5e0b8f", caption=False), BOT_MODES),
        (Tile("Demo", "🤖", "#64d2ff", "#0a3d62", caption=False), BOT_MODES),
        (Tile("Discovery", "🤖", "#ffd60a", "#ff6a00", caption=False), BOT_MODES),
        (Tile("Jazz", "🤖", "#bf5af2", "#1f1147", caption=False), BOT_MODES),
        (Tile("Laidback", "🤖", "#30d158", "#0b5345", caption=False), BOT_MODES),
        (Tile("Songwriters", "🤖", "#ff9f0a", "#7b2d00", caption=False), BOT_MODES),
        (Tile("Vocal", "🤖", "#ff375f", "#3d0a1f", caption=False), BOT_MODES),
    ],
    "folders": [
        (Tile("Favourites", "⭐", "#fa2d48", "#7a0f1e", caption=False), ()),
        (Tile("Mine", "📚", "#8e2de2", "#2b0a4a", caption=False), ()),
        (Tile("Curated", "🧭", "#0a84ff", "#0b2a55", caption=False), ()),
        (Tile("Mellow", "🎹", "#8e2de2", "#2b0a4a", caption=False), ()),
    ],
    "work": [
        (Tile("Headspace", "🧠", "#5e5ce6", "#1b1a4d", caption=False), ()),
        (Tile("Electronic Daily", "⚡", "#00c7be", "#00413e", caption=False), ()),
        (Tile("Flow State", "🌊", "#0a84ff", "#002a5c", caption=False), ()),
        (Tile("Classical Concentration", "🎻", "#c9a227", "#4a3500", caption=False), ()),
        (Tile("Meditation Moments", "🧘", "#34c759", "#0d3d1c", caption=False), ()),
    ],
    "club": [
        (Tile("Melodic House & Techno", "🎛️", "#bf5af2", "#2a0b45", caption=False), ()),
        (Tile("Chilltronics", "🌙", "#5ac8fa", "#0c2d4a", caption=False), ()),
        (Tile("BEATstrumentals", "🥁", "#ff453a", "#4d0a06", caption=False), ()),
    ],
    "now": [(Tile("Favourite Songs", "❤️", "#fa2d48", "#5c0a1a", caption=False), ())],
    "stations": [
        (Tile("Aphex Twin", "📡", "#3a3a3c", "#000000", caption=False), ()),
        (Tile("Tord Gustavsen", "📡", "#1c3d5a", "#050d14", caption=False), ()),
        (Tile("Pat Metheny", "📡", "#7a4a1c", "#1f1105", caption=False), ()),
    ],
}

HOME_NAV: dict[str, tuple[str, str]] = {
    "Utils": ("🛠️", "left"),
    "Messages": ("💬", "up"),
    "Music": ("🎵", "right"),
}


def generate(out: Path, size: int = BASE) -> int:
    """Write every generated icon under out/<group>/. Returns the count."""
    count = 0

    def save(image: Image.Image, group: str, name: str) -> None:
        nonlocal count
        (out / group).mkdir(parents=True, exist_ok=True)
        image.save(out / group / f"{name}.png")
        count += 1

    save(render_skip(size), "controls", "Skip")
    # More is a normal Bot tile; like every folder key it gets its arrow at render time.
    save(render_tile(Tile("More", "🤖", "#636366", "#1c1c1e", caption=False), size), "bot", "More")
    for name, (emoji, direction) in HOME_NAV.items():
        save(render_home_nav(emoji, direction, size), "nav", name)
    for group, group_tiles in TILES.items():
        for t, modes in group_tiles:
            save(render_tile(t, size), group, t.name)
            for mode in modes:
                save(
                    render_tile(Tile(t.name, t.glyph, t.start, t.end, mode, caption=False), size),
                    group,
                    f"{t.name} {mode}",
                )
    return count


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "icons"
    print(f"wrote {generate(out)} icons under {out}")


if __name__ == "__main__":
    main()
