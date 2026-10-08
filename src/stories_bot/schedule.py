"""Schedule parsing and the "what is due right now" decision."""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # index == date.weekday()
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov"})

DEFAULT_TIMEZONE = "America/Sao_Paulo"
DEFAULT_WINDOW_MINUTES = 30
MAX_WINDOW_MINUTES = 12 * 60


class ScheduleError(ValueError):
    """The schedule file is missing fields or contains invalid values."""


@dataclass(frozen=True)
class Slot:
    """One recurring Story: which weekdays, at what local time, which media file."""

    days: frozenset[str]
    at: time
    file: str

    @property
    def is_video(self) -> bool:
        return Path(self.file).suffix.lower() in VIDEO_EXTENSIONS

    def key(self, day: date) -> str:
        """Idempotency key: the same slot on the same day is published only once."""
        return f"{day.isoformat()}|{self.at:%H:%M}|{self.file}"


@dataclass(frozen=True)
class Schedule:
    timezone: ZoneInfo
    window: timedelta
    slots: tuple[Slot, ...]


@dataclass(frozen=True)
class DueStory:
    slot: Slot
    key: str


def _parse_slot(raw: Any, index: int) -> Slot:
    where = f"stories[{index}]"
    if not isinstance(raw, dict):
        raise ScheduleError(f"{where}: expected an object")
    missing = {"days", "time", "file"} - raw.keys()
    if missing:
        raise ScheduleError(f"{where}: missing field(s) {sorted(missing)}")

    days = raw["days"]
    if not isinstance(days, list) or not days or not set(days) <= set(WEEKDAYS):
        raise ScheduleError(f"{where}: 'days' must be a non-empty list of {list(WEEKDAYS)}")

    try:
        at = datetime.strptime(str(raw["time"]), "%H:%M").time()
    except ValueError:
        raise ScheduleError(f"{where}: 'time' must be HH:MM (24h), got {raw['time']!r}") from None

    file = raw["file"]
    suffix = Path(str(file)).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
        raise ScheduleError(f"{where}: unsupported media type {suffix or file!r}")

    return Slot(days=frozenset(days), at=at, file=str(file))


def parse_schedule(data: Any) -> Schedule:
    if not isinstance(data, dict):
        raise ScheduleError("schedule must be a JSON object")

    try:
        tz = ZoneInfo(data.get("timezone", DEFAULT_TIMEZONE))
    except (ZoneInfoNotFoundError, ValueError):
        raise ScheduleError(f"unknown timezone {data.get('timezone')!r}") from None

    minutes = data.get("window_minutes", DEFAULT_WINDOW_MINUTES)
    if not isinstance(minutes, int) or not 1 <= minutes <= MAX_WINDOW_MINUTES:
        raise ScheduleError(f"'window_minutes' must be an integer in 1..{MAX_WINDOW_MINUTES}")

    raw_slots = data.get("stories", [])
    if not isinstance(raw_slots, list):
        raise ScheduleError("'stories' must be a list")

    slots = tuple(_parse_slot(raw, i) for i, raw in enumerate(raw_slots))
    return Schedule(timezone=tz, window=timedelta(minutes=minutes), slots=slots)


def load_schedule(path: Path) -> Schedule:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScheduleError(f"{path} is not valid JSON: {exc}") from exc
    return parse_schedule(data)


def due_stories(
    schedule: Schedule, now: datetime, already_posted: Collection[str]
) -> list[DueStory]:
    """Slots whose start time has passed no more than `window` ago and are not yet posted.

    The scheduler (GitHub Actions cron) is not punctual, so a slot stays eligible for the
    whole window. Yesterday is checked too, so a 23:50 slot still fires after midnight.
    """
    now = now.astimezone(schedule.timezone)
    due: list[DueStory] = []
    for slot in schedule.slots:
        for days_ago in (0, 1):
            day = now.date() - timedelta(days=days_ago)
            if WEEKDAYS[day.weekday()] not in slot.days:
                continue
            start = datetime.combine(day, slot.at, tzinfo=schedule.timezone)
            key = slot.key(day)
            if start <= now < start + schedule.window and key not in already_posted:
                due.append(DueStory(slot=slot, key=key))
    return due
