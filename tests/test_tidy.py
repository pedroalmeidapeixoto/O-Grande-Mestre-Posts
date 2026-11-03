import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stories_bot import tidy
from stories_bot.state import load_missed, prune_records, record_missed

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=TZ)


@pytest.fixture
def project(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    for name in ("old.jpg", "recent.jpg", "future.jpg", "shared.jpg", "weekly.jpg", "README.md"):
        (media / name).write_bytes(b"art")
    (tmp_path / "schedule.json").write_text(
        json.dumps(
            {
                "timezone": "America/Sao_Paulo",
                "stories": [
                    {"date": "2026-11-01", "time": "10:00", "file": "old.jpg"},
                    {"date": "2026-11-08", "time": "10:00", "file": "recent.jpg"},  # 2 days ago
                    {"date": "2026-11-12", "time": "10:00", "file": "future.jpg"},
                    {"date": "2026-11-02", "time": "10:00", "file": "shared.jpg"},
                    {"days": ["mon"], "time": "10:00", "file": "shared.jpg"},
                    {"days": ["fri"], "time": "18:00", "file": "weekly.jpg"},
                ],
            }
        )
    )
    return tmp_path


def run_tidy(project, now=NOW):
    return tidy.tidy(
        project / "schedule.json",
        project / "media",
        project / "state" / "posted.json",
        project / "state" / "attempts.json",
        project / "state" / "missed.json",
        now,
    )


def test_old_one_offs_and_their_arts_are_removed(project):
    result = run_tidy(project)

    files = [s["file"] for s in json.loads((project / "schedule.json").read_text())["stories"]]
    assert files == ["recent.jpg", "future.jpg", "shared.jpg", "weekly.jpg"]
    assert result["stories"] == 2 and result["arts"] == 1
    assert not (project / "media" / "old.jpg").exists()


def test_arts_still_used_or_not_owned_are_kept(project):
    run_tidy(project)

    media = project / "media"
    for name in ("recent.jpg", "future.jpg", "weekly.jpg", "README.md"):
        assert (media / name).exists()
    assert (media / "shared.jpg").exists()  # its weekly entry still uses it


def test_state_records_are_pruned_by_age(project):
    state = project / "state"
    state.mkdir()
    (state / "posted.json").write_text(
        json.dumps(
            {
                "old": {"posted_at": "2026-09-01T10:00:00-03:00"},
                "new": {"posted_at": "2026-11-09T10:00:00-03:00"},
            }
        )
    )
    (state / "attempts.json").write_text(
        json.dumps(
            {
                "old": {"count": 3, "last_attempt": "2026-11-01T10:00:00-03:00"},
                "new": {"count": 1, "last_attempt": "2026-11-09T10:00:00-03:00"},
            }
        )
    )
    (state / "missed.json").write_text(
        json.dumps({"old": "2026-11-01T10:00:00-03:00", "new": "2026-11-09T10:00:00-03:00"})
    )

    result = run_tidy(project)

    assert result["posted"] == result["attempts"] == result["missed"] == 1
    for name in ("posted", "attempts", "missed"):
        assert list(json.loads((state / f"{name}.json").read_text())) == ["new"]


def test_nothing_to_do_changes_nothing(project):
    run_tidy(project)
    before = (project / "schedule.json").read_text()

    result = run_tidy(project)

    assert not any(result.values())
    assert (project / "schedule.json").read_text() == before


def test_prune_records_keeps_unreadable_timestamps(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(
        json.dumps({"a": {}, "b": {"t": "garbage"}, "c": {"t": "2020-01-01T00:00:00+00:00"}})
    )

    dropped = prune_records(path, NOW, lambda v: v["t"])

    assert dropped == 1
    assert sorted(json.loads(path.read_text())) == ["a", "b"]
    assert prune_records(tmp_path / "missing.json", NOW, lambda v: v) == 0


def test_missed_records_roundtrip(tmp_path):
    path = tmp_path / "state" / "missed.json"
    assert load_missed(path) == {}
    record_missed(path, "k", NOW)
    assert load_missed(path) == {"k": NOW.isoformat()}


def test_cli_tidies_and_reports(project, caplog):
    code = tidy.main(
        [
            "--schedule", str(project / "schedule.json"),
            "--media-dir", str(project / "media"),
            "--state", str(project / "state" / "posted.json"),
            "--attempts", str(project / "state" / "attempts.json"),
            "--missed", str(project / "state" / "missed.json"),
            "--now", "2026-11-10T12:00",
        ]
    )  # fmt: skip

    assert code == tidy.EXIT_OK
    assert not (project / "media" / "old.jpg").exists()


def test_cli_reports_a_bad_schedule(project):
    (project / "schedule.json").write_text("{not json")
    assert tidy.main(["--schedule", str(project / "schedule.json")]) == tidy.EXIT_BAD_SETUP
