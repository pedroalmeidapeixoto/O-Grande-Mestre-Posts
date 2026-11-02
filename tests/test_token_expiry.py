import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from stories_bot.token_expiry import days_left, reminder_due

TZ = ZoneInfo("America/Sao_Paulo")


def at(month: int, day: int) -> datetime:
    return datetime(2026, month, day, 12, 0, tzinfo=TZ)


def test_days_left_counts_from_the_issue_date():
    assert days_left(date(2026, 10, 8), date(2026, 10, 8)) == 60
    assert days_left(date(2026, 10, 8), date(2026, 12, 7)) == 0
    assert days_left(date(2026, 10, 8), date(2026, 12, 9)) == -2


def test_nothing_to_say_when_unset_invalid_or_far_from_expiry(tmp_path):
    state = tmp_path / "reminders.json"
    assert reminder_due({}, at(11, 1), state) is None
    assert reminder_due({"IG_TOKEN_ISSUED": "08/10/2026"}, at(11, 1), state) is None
    assert reminder_due({"IG_TOKEN_ISSUED": "2026-10-08"}, at(11, 1), state) is None  # 36 days left
    assert not state.exists()


def test_warns_inside_the_last_ten_days(tmp_path):
    env = {"IG_TOKEN_ISSUED": "2026-10-08"}
    message = reminder_due(env, at(11, 27), tmp_path / "reminders.json")  # 10 days left

    assert message is not None
    assert "vence em 10 dia(s)" in message and "stories-token" in message


def test_warns_only_once_a_day(tmp_path):
    env = {"IG_TOKEN_ISSUED": "2026-10-08"}
    state = tmp_path / "reminders.json"

    assert reminder_due(env, at(12, 1), state) is not None
    assert reminder_due(env, at(12, 1), state) is None  # same day, later run
    assert reminder_due(env, at(12, 2), state) is not None  # next day
    assert json.loads(state.read_text())["token_expiry"] == "2026-12-02"


def test_reports_an_expired_token(tmp_path):
    env = {"IG_TOKEN_ISSUED": "2026-10-08"}
    message = reminder_due(env, at(12, 10), tmp_path / "reminders.json")

    assert message is not None and message.startswith("❌") and "venceu" in message
