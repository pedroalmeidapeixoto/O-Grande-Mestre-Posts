import pytest

from stories_bot.media import image_size, is_story_ratio


def png(width, height):
    header = b"\x00\x00\x00\rIHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big")
    return b"\x89PNG\r\n\x1a\n" + header + b"\x08\x06\x00\x00\x00"


def jpeg(width, height):
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00" + b"\x00" * 9  # skipped segment
    sof = b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08"
    sof += height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + app0 + sof


def test_png_and_jpeg_sizes():
    assert image_size(png(1080, 1920)) == (1080, 1920)
    assert image_size(jpeg(1024, 1536)) == (1024, 1536)


@pytest.mark.parametrize(
    "data", [b"", b"GIF89a....", b"\x89PNG\r\n\x1a\n", b"\xff\xd8", b"\xff\xd8\xff\xe0"]
)
def test_unreadable_images_return_none(data):
    assert image_size(data) is None


@pytest.mark.parametrize(
    ("width", "height", "ok"),
    [
        (1080, 1920, True),
        (720, 1280, True),
        (1079, 1920, True),
        (1024, 1536, False),
        (1920, 1080, False),
        (10, 0, False),
    ],
)
def test_story_ratio(width, height, ok):
    assert is_story_ratio(width, height) is ok
