import json

import pytest

from stories_bot import cli
from stories_bot.instagram import InstagramClient, InstagramError

FRIDAY_18_05 = "2026-10-09T18:05"


@pytest.fixture
def project(tmp_path, monkeypatch):
    for name in ("IG_USER_ID", "IG_ACCESS_TOKEN", "MEDIA_BASE_URL", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(name, raising=False)
    media = tmp_path / "media"
    media.mkdir()
    (media / "promo.jpg").write_bytes(b"jpg")
    schedule = tmp_path / "schedule.json"
    schedule.write_text(
        json.dumps({"stories": [{"days": ["fri"], "time": "18:00", "file": "promo.jpg"}]})
    )
    return tmp_path


def run(project, *extra):
    return cli.main(
        [
            "--schedule", str(project / "schedule.json"),
            "--media-dir", str(project / "media"),
            "--state", str(project / "state" / "posted.json"),
            "--now", FRIDAY_18_05,
            *extra,
        ]
    )  # fmt: skip


def configure(monkeypatch):
    monkeypatch.setenv("IG_USER_ID", "1")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "t")
    monkeypatch.setenv("MEDIA_BASE_URL", "https://h/media")


def test_dry_run_publishes_nothing_and_needs_no_credentials(project):
    assert run(project, "--dry-run") == cli.EXIT_OK
    assert not (project / "state").exists()


def test_publishes_once_then_is_idempotent(project, monkeypatch):
    configure(monkeypatch)
    calls = []

    def fake_publish(self, url, *, is_video):
        calls.append((url, is_video))
        return "m1"

    monkeypatch.setattr(InstagramClient, "publish_story", fake_publish)

    assert run(project) == cli.EXIT_OK
    assert run(project) == cli.EXIT_OK  # second run: already posted
    assert calls == [("https://h/media/promo.jpg", False)]
    posted = json.loads((project / "state" / "posted.json").read_text())
    assert next(iter(posted.values()))["media_id"] == "m1"


def test_failure_is_reported_and_not_recorded(project, monkeypatch):
    configure(monkeypatch)

    def boom(self, url, *, is_video):
        raise InstagramError("HTTP 400: nope")

    monkeypatch.setattr(InstagramClient, "publish_story", boom)

    assert run(project) == cli.EXIT_FAILED
    assert not (project / "state" / "posted.json").exists()


def test_missing_media_file_fails(project):
    (project / "media" / "promo.jpg").unlink()
    assert run(project, "--dry-run") == cli.EXIT_FAILED


def test_missing_credentials_is_a_setup_error(project):
    assert run(project) == cli.EXIT_BAD_SETUP


def test_invalid_schedule_is_a_setup_error(project):
    (project / "schedule.json").write_text("{not json")
    assert run(project) == cli.EXIT_BAD_SETUP


def test_nothing_due_succeeds_without_credentials(project):
    code = cli.main(
        [
            "--schedule", str(project / "schedule.json"),
            "--media-dir", str(project / "media"),
            "--state", str(project / "state" / "posted.json"),
            "--now", "2026-10-09T12:00",
        ]
    )  # fmt: skip
    assert code == cli.EXIT_OK
