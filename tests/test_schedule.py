from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stories_bot.schedule import ScheduleError, due_stories, parse_schedule

TZ = ZoneInfo("America/Sao_Paulo")


def make_schedule(*stories: dict, window_minutes: int = 30):
    return parse_schedule(
        {
            "timezone": "America/Sao_Paulo",
            "window_minutes": window_minutes,
            "stories": list(stories),
        }
    )


FRIDAY_PROMO = {"days": ["fri", "sat"], "time": "18:00", "file": "promo.jpg"}


def at(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)  # 2026-10-09 is a Friday


def test_due_inside_the_window():
    due = due_stories(make_schedule(FRIDAY_PROMO), at(9, 18, 5), set())
    assert [d.slot.file for d in due] == ["promo.jpg"]
    assert due[0].key == "2026-10-09|18:00|promo.jpg"


@pytest.mark.parametrize(
    ("day", "hour", "minute"),
    [(9, 17, 59), (9, 18, 30), (9, 23, 0), (8, 18, 5)],  # before, at window end, late, Thursday
)
def test_not_due_outside_window_or_day(day, hour, minute):
    assert due_stories(make_schedule(FRIDAY_PROMO), at(day, hour, minute), set()) == []


def test_already_posted_is_skipped():
    key = "2026-10-09|18:00|promo.jpg"
    assert due_stories(make_schedule(FRIDAY_PROMO), at(9, 18, 5), {key}) == []


def test_slot_just_before_midnight_still_fires_after_midnight():
    late = {"days": ["fri"], "time": "23:50", "file": "late.jpg"}
    due = due_stories(make_schedule(late), at(10, 0, 5), set())  # Saturday 00:05
    assert [d.key for d in due] == ["2026-10-09|23:50|late.jpg"]


def test_now_is_converted_to_schedule_timezone():
    utc_now = datetime(2026, 10, 9, 21, 5, tzinfo=ZoneInfo("UTC"))  # 18:05 in São Paulo
    assert len(due_stories(make_schedule(FRIDAY_PROMO), utc_now, set())) == 1


def test_video_detection():
    schedule = make_schedule({"days": ["sun"], "time": "11:00", "file": "lunch.MP4"}, FRIDAY_PROMO)
    assert [s.is_video for s in schedule.slots] == [True, False]


@pytest.mark.parametrize(
    "story",
    [
        {"days": ["fri"], "time": "18:00"},  # missing file
        {"days": [], "time": "18:00", "file": "a.jpg"},  # empty days
        {"days": ["friday"], "time": "18:00", "file": "a.jpg"},  # bad weekday
        {"days": "fri", "time": "18:00", "file": "a.jpg"},  # days not a list
        {"days": ["fri"], "time": "6pm", "file": "a.jpg"},  # bad time
        {"days": ["fri"], "time": "25:00", "file": "a.jpg"},  # impossible time
        {"days": ["fri"], "time": "18:00", "file": "a.gif"},  # unsupported media
    ],
)
def test_invalid_slots_are_rejected(story):
    with pytest.raises(ScheduleError):
        make_schedule(story)


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"timezone": "Mars/Olympus"},
        {"window_minutes": 0},
        {"window_minutes": "30"},
        {"stories": {}},
    ],
)
def test_invalid_top_level_is_rejected(data):
    with pytest.raises(ScheduleError):
        parse_schedule(data)


def test_empty_schedule_is_valid():
    assert parse_schedule({}).slots == ()
