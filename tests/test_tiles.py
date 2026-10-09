from PIL import Image

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
