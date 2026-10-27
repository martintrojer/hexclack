import random

from PIL import Image, ImageDraw

from hexclack import tiles


def _no_files(*_args, **_kwargs):
    raise AssertionError("render_skip must not read image files")


def _brightest(image: Image.Image) -> int:
    histogram = image.convert("L").histogram()
    return max(level for level, count in enumerate(histogram) if count)


def _peak(image: Image.Image, box: tuple[int, int, int, int]) -> int:
    return _brightest(image.crop(box))


def test_render_skip_draws_without_reading_files(monkeypatch):
    monkeypatch.setattr(Image, "open", _no_files)
    for size in (72, 80, 288):
        image = tiles.render_skip(size)
        assert image.mode == "RGB"
        assert image.size == (size, size)


def test_render_skip_has_large_white_next_over_grey_prev_and_shuffle():
    size = tiles.BASE
    image = tiles.render_skip(size)
    half, bottom = size // 2, size - tiles._px(24, size)
    small_top = bottom - tiles._px(64, size)

    # Large Next mark in the upper part is full white.
    assert _peak(image, (0, 0, size, small_top)) == 255
    # Previous (bottom left) and Shuffle (bottom right) are both drawn, dimmed to grey.
    prev = image.crop((0, small_top, half, bottom)).convert("L")
    shuffle = image.crop((half, small_top, size, bottom)).convert("L")
    for mark in (prev, shuffle):
        assert 100 < _brightest(mark) < 200
    # They are different shapes, not the same mark twice.
    assert prev.tobytes() != shuffle.transpose(Image.Transpose.FLIP_LEFT_RIGHT).tobytes()
    # Corners stay black.
    assert _peak(image, (0, 0, 10, 10)) == 0
    assert _peak(image, (size - 10, size - 10, size, size)) == 0


def test_render_skip_is_deterministic():
    assert tiles.render_skip(80).tobytes() == tiles.render_skip(80).tobytes()


def test_caption_false_omits_name_text():
    named = tiles.render_tile(tiles.Tile("Favourites", "⭐", "#fa2d48", "#7a0f1e"), size=80)
    plain = tiles.render_tile(tiles.Tile("Favourites", "⭐", "#fa2d48", "#7a0f1e", caption=False), size=80)
    assert named.tobytes() != plain.tobytes()
    # Same glyph/colours with caption draws the name into the bottom-left corner.
    assert named.crop((0, 55, 40, 80)).tobytes() != plain.crop((0, 55, 40, 80)).tobytes()


def test_pick_tile_differs_by_category():
    palette = tiles.shuffled_colors(["Lanes", "Canon"], rng=random.Random(0))
    a = tiles.pick_tile("Flow State", "Lanes", size=80, bg=palette["Lanes"])
    b = tiles.pick_tile("Flow State", "Canon", size=80, bg=palette["Canon"])
    assert a.tobytes() != b.tobytes()
    assert a.size == (80, 80)
    assert a.getpixel((0, 0)) == palette["Lanes"]
    assert b.getpixel((0, 0)) == palette["Canon"]


def test_shuffled_colors_separates_live_set():
    cats = [
        "Any",
        "Lanes",
        "Canon",
        "Club",
        "Discovery",
        "Klara & Julia",
        "Nordic",
        "Other",
        "Soundtracks",
        "Now",
        "Seasonal",
    ]
    palette = tiles.shuffled_colors(cats, rng=random.Random(1))
    assert set(palette) == set(cats)
    # Same rng → same mapping; different open can reshuffle.
    assert palette == tiles.shuffled_colors(cats, rng=random.Random(1))
    assert palette != tiles.shuffled_colors(cats, rng=random.Random(2))
    rgbs = list(palette.values())
    closest = min(
        sum((a - b) ** 2 for a, b in zip(u, v, strict=True)) ** 0.5 for i, u in enumerate(rgbs) for v in rgbs[i + 1 :]
    )
    assert closest > 25


def test_pick_tile_long_name_shares_category_tint():
    long = "Supercalifragilistic " * 8
    bg = tiles.shuffled_colors(["Lanes", "Canon"], rng=random.Random(0))["Lanes"]
    img = tiles.pick_tile(long.strip(), "Lanes", size=80, bg=bg)
    assert img.size == (80, 80)
    assert img.getpixel((0, 0)) == bg
    draw = ImageDraw.Draw(img)
    font, lines = tiles.fit_pick_name(draw, long.strip(), width=60, largest=40, smallest=20)
    assert len(lines) <= 2
    assert all(draw.textlength(line, font=font) <= 60 for line in lines)


def test_playlist_tile_uses_bg():
    bg = tiles.shuffled_colors(["a", "b"], rng=random.Random(0))["a"]
    img = tiles.playlist_tile("DNA", "Sep 28", "2026", size=80, bg=bg)
    assert img.getpixel((0, 0)) == bg
