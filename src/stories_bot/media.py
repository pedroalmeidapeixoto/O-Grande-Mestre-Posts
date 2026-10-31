"""Just enough image parsing to check the aspect ratio of an art without extra dependencies."""

from __future__ import annotations

STORY_RATIO = 9 / 16
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SOF = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def image_size(data: bytes) -> tuple[int, int] | None:
    """Return (width, height) of a PNG or JPEG from its header, or None if unreadable."""
    if data.startswith(_PNG_SIGNATURE) and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data.startswith(b"\xff\xd8"):
        return _jpeg_size(data)
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 9 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in _JPEG_SOF:
            height = int.from_bytes(data[i + 5 : i + 7], "big")
            width = int.from_bytes(data[i + 7 : i + 9], "big")
            return width, height
        if marker == 0xFF:  # fill byte
            i += 1
        elif marker == 0x01 or 0xD0 <= marker <= 0xD9:  # markers without a length
            i += 2
        else:
            i += 2 + int.from_bytes(data[i + 2 : i + 4], "big")
    return None


def is_story_ratio(width: int, height: int, tolerance: float = 0.02) -> bool:
    """True when the image is 9:16 within `tolerance` (relative)."""
    return height > 0 and abs(width / height - STORY_RATIO) <= STORY_RATIO * tolerance
