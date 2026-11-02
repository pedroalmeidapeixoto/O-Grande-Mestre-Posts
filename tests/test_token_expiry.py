import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from stories_bot.token_expiry import days_left, reminder_due

TZ = ZoneInfo("America/Sao_Paulo")
ENV = {"IG_TOKEN_EXPIRES": "2026-12-31"}


def at(month: int, day: int) -> datetime:
    return datetime(2026, month, day, 12, 0, tzinfo=TZ)


def test_days_left_counts_to_the_expiry_date():
    assert days_left(date(2026, 12, 31), date(2026, 12, 21)) == 10
    assert days_left(date(2026, 12, 31), date(2026, 12, 31)) == 0
    assert days_left(date(2026, 12, 31), date(2027, 1, 2)) == -2


def test_nothing_to_say_when_unset_invalid_or_far_from_expiry(tmp_path):
    state = tmp_path / "reminders.json"
    assert reminder_due({}, at(11, 2), state) is None
    assert reminder_due({"IG_TOKEN_EXPIRES": "31/12/2026"}, at(12, 25), state) is None
    assert reminder_due(ENV, at(12, 20), state) is None  # 11 days left
    assert not state.exists()


def test_warns_inside_the_last_ten_days(tmp_path):
    message = reminder_due(ENV, at(12, 21), tmp_path / "reminders.json")  # 10 days left

    assert message is not None
    assert "vence em 10 dia(s)" in message and "stories-token" in message


def test_warns_only_once_a_day(tmp_path):
    state = tmp_path / "reminders.json"

    assert reminder_due(ENV, at(12, 25), state) is not None
    assert reminder_due(ENV, at(12, 25), state) is None  # same day, later run
    assert reminder_due(ENV, at(12, 26), state) is not None  # next day
    assert json.loads(state.read_text())["token_expiry"] == "2026-12-26"


def test_reports_the_expiry_day_and_after(tmp_path):
    today = reminder_due(ENV, at(12, 31), tmp_path / "a.json")
    later = reminder_due(ENV, datetime(2027, 1, 3, 9, 0, tzinfo=TZ), tmp_path / "b.json")

    assert today is not None and today.startswith("❌") and "vence hoje" in today
    assert later is not None and later.startswith("❌") and "há 3 dia(s)" in later
