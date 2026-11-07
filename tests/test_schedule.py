import json
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from stories_bot.schedule import (
    ScheduleError,
    add_one_off,
    due_stories,
    missed_stories,
    parse_schedule,
    prune_one_offs,
)

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
        {"time": "18:00", "file": "a.jpg"},  # neither days nor date
        {"days": ["fri"], "date": "2026-10-09", "time": "18:00", "file": "a.jpg"},  # both
        {"date": "09/10/2026", "time": "18:00", "file": "a.jpg"},  # bad date format
        {"date": "2026-02-30", "time": "18:00", "file": "a.jpg"},  # impossible date
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


ONE_OFF = {"date": "2026-10-09", "time": "18:00", "file": "holiday.jpg"}


def test_one_off_is_due_only_on_its_date():
    schedule = make_schedule(ONE_OFF)
    assert [d.key for d in due_stories(schedule, at(9, 18, 5), set())] == [
        "2026-10-09|18:00|holiday.jpg"
    ]
    # the same weekday a week later must not fire again
    assert due_stories(schedule, datetime(2026, 10, 16, 18, 5, tzinfo=TZ), set()) == []


def test_one_off_is_published_once():
    schedule = make_schedule(ONE_OFF)
    assert due_stories(schedule, at(9, 18, 5), {"2026-10-09|18:00|holiday.jpg"}) == []


def test_one_off_just_before_midnight_still_fires_after_midnight():
    late = {"date": "2026-10-09", "time": "23:50", "file": "late.jpg"}
    assert len(due_stories(make_schedule(late, window_minutes=60), at(10, 0, 5), set())) == 1


def test_empty_schedule_is_valid():
    assert parse_schedule({}).slots == ()


def test_missed_stories_lists_windows_that_closed_recently():
    schedule = make_schedule(FRIDAY_PROMO)  # 30 min window
    assert missed_stories(schedule, at(9, 18, 29), set()) == []  # window still open
    lost = missed_stories(schedule, at(9, 18, 30), set())
    assert [m.key for m in lost] == ["2026-10-09|18:00|promo.jpg"]
    assert lost[0].start == at(9, 18, 0)
    assert missed_stories(schedule, at(9, 23, 59), set()) != []  # 5h29 after it closed
    assert missed_stories(schedule, at(10, 0, 31), set()) == []  # over the 6h lookback


def test_missed_stories_ignores_posted_and_wrong_days():
    schedule = make_schedule(FRIDAY_PROMO)
    assert missed_stories(schedule, at(9, 19, 0), {"2026-10-09|18:00|promo.jpg"}) == []
    assert missed_stories(schedule, at(8, 19, 0), set()) == []  # a Thursday


def test_missed_stories_covers_one_offs_and_the_previous_day():
    late = {"date": "2026-10-09", "time": "23:50", "file": "late.jpg"}
    lost = missed_stories(make_schedule(late), at(10, 0, 30), set())  # Saturday 00:30
    assert [m.key for m in lost] == ["2026-10-09|23:50|late.jpg"]


def test_prune_one_offs_removes_only_old_dated_entries(tmp_path):
    path = tmp_path / "schedule.json"
    path.write_text(
        json.dumps(
            {
                "stories": [
                    {"date": "2026-10-01", "time": "10:00", "file": "old.jpg"},
                    {"date": "2026-10-09", "time": "10:00", "file": "today.jpg"},
                    {"days": ["fri"], "time": "18:00", "file": "weekly.jpg"},
                ]
            }
        )
    )

    assert prune_one_offs(path, date(2026, 10, 7)) == ["old.jpg"]
    assert [s["file"] for s in json.loads(path.read_text())["stories"]] == [
        "today.jpg",
        "weekly.jpg",
    ]
    assert prune_one_offs(path, date(2026, 10, 7)) == []


def test_caption_is_optional_and_kept():
    plain = make_schedule(FRIDAY_PROMO).slots[0]
    texted = make_schedule({**FRIDAY_PROMO, "caption": "Bora?"}).slots[0]
    assert plain.caption is None and texted.caption == "Bora?"


@pytest.mark.parametrize("caption", ["", "   ", 5, ["a"], "x" * 4001])
def test_unusable_captions_are_rejected(caption):
    with pytest.raises(ScheduleError, match="caption"):
        make_schedule({**FRIDAY_PROMO, "caption": caption})


def test_add_one_off_stores_the_caption_only_when_given(tmp_path):
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps({"stories": []}), encoding="utf-8")

    add_one_off(path, date(2026, 11, 9), time(10, 0), "a.jpg")
    add_one_off(path, date(2026, 11, 9), time(10, 0), "b.jpg", "Cardápio 🍽️")

    stories = json.loads(path.read_text(encoding="utf-8"))["stories"]
    assert "caption" not in stories[0] and stories[1]["caption"] == "Cardápio 🍽️"
