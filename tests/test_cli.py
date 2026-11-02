import json

import pytest

from stories_bot import cli
from stories_bot.instagram import InstagramClient, InstagramError
from stories_bot.notify import TelegramNotifier

FRIDAY_18_05 = "2026-10-09T18:05"


@pytest.fixture
def project(tmp_path, monkeypatch):
    for name in (
        "IG_USER_ID",
        "IG_ACCESS_TOKEN",
        "MEDIA_BASE_URL",
        "GITHUB_REPOSITORY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "IG_TOKEN_EXPIRES",
    ):
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
            "--attempts", str(project / "state" / "attempts.json"),
            "--reminders", str(project / "state" / "reminders.json"),
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


@pytest.fixture
def sent(monkeypatch):
    """Telegram is configured and every message is captured instead of being sent."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-secret")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    messages: list[str] = []
    monkeypatch.setattr(TelegramNotifier, "send", lambda self, text: messages.append(text))
    return messages


def test_success_sends_a_notification(project, monkeypatch, sent):
    configure(monkeypatch)
    monkeypatch.setattr(InstagramClient, "publish_story", lambda self, url, *, is_video: "m1")

    assert run(project) == cli.EXIT_OK
    assert sent == ["✅ Story publicado: promo.jpg (09/10 18:05)"]


def test_failure_sends_a_notification(project, monkeypatch, sent):
    configure(monkeypatch)

    def boom(self, url, *, is_video):
        raise InstagramError("HTTP 400: nope")

    monkeypatch.setattr(InstagramClient, "publish_story", boom)

    assert run(project) == cli.EXIT_FAILED
    assert sent == [
        "❌ Falha ao publicar promo.jpg: HTTP 400: nope."
        " Tentativa 1 de 3; tento de novo na próxima rodada."
    ]


def test_missing_credentials_sends_a_notification(project, sent):
    assert run(project) == cli.EXIT_BAD_SETUP
    assert len(sent) == 1 and sent[0].startswith("❌ Story não publicado: configuração")


def test_dry_run_and_nothing_due_send_no_notification(project, sent):
    assert run(project, "--dry-run") == cli.EXIT_OK
    code = cli.main(
        [
            "--schedule", str(project / "schedule.json"),
            "--media-dir", str(project / "media"),
            "--state", str(project / "state" / "posted.json"),
            "--now", "2026-10-09T12:00",
        ]
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert sent == []


def attempts_of(project):
    return json.loads((project / "state" / "attempts.json").read_text())


def failing_publish(monkeypatch, message="HTTP 400: nope", code=None):
    def boom(self, url, *, is_video):
        raise InstagramError(message, code)

    monkeypatch.setattr(InstagramClient, "publish_story", boom)


def test_a_failing_story_is_retried_then_given_up(project, monkeypatch, sent):
    configure(monkeypatch)
    failing_publish(monkeypatch)

    for _ in range(3):
        assert run(project) == cli.EXIT_FAILED
    assert next(iter(attempts_of(project).values()))["count"] == 3
    assert "Tentativa 1 de 3" in sent[0] and "Desisti" in sent[2]

    # given up: the next run does not try (or complain) again
    assert run(project) == cli.EXIT_OK
    assert len(sent) == 3


def test_a_successful_retry_is_published(project, monkeypatch, sent):
    configure(monkeypatch)
    failing_publish(monkeypatch)
    assert run(project) == cli.EXIT_FAILED

    monkeypatch.setattr(InstagramClient, "publish_story", lambda self, url, *, is_video: "m1")
    assert run(project) == cli.EXIT_OK
    assert sent[-1].startswith("✅")


def test_expired_token_stops_without_counting_attempts(project, monkeypatch, sent):
    configure(monkeypatch)
    failing_publish(monkeypatch, "HTTP 400: Error validating access token", code=190)

    assert run(project) == cli.EXIT_BAD_SETUP
    assert not (project / "state" / "attempts.json").exists()
    assert len(sent) == 1 and "recusou o token" in sent[0] and "stories-token" in sent[0]


def test_missing_media_is_counted_and_given_up(project, sent):
    (project / "media" / "promo.jpg").unlink()
    for _ in range(3):
        assert run(project) == cli.EXIT_FAILED

    assert next(iter(attempts_of(project).values()))["count"] == 3
    assert "não encontrado" in sent[0] and "Desisti" in sent[2]
    assert run(project) == cli.EXIT_OK


def test_dry_run_does_not_count_attempts(project):
    (project / "media" / "promo.jpg").unlink()
    assert run(project, "--dry-run") == cli.EXIT_FAILED
    assert not (project / "state" / "attempts.json").exists()


def test_token_reminder_is_sent_even_when_nothing_is_due(project, monkeypatch, sent):
    monkeypatch.setenv("IG_TOKEN_EXPIRES", "2026-10-19")  # 10 days after the pretend "now"
    code = cli.main(
        [
            "--schedule", str(project / "schedule.json"),
            "--media-dir", str(project / "media"),
            "--state", str(project / "state" / "posted.json"),
            "--attempts", str(project / "state" / "attempts.json"),
            "--reminders", str(project / "state" / "reminders.json"),
            "--now", "2026-10-09T12:00",
        ]
    )  # fmt: skip
    assert code == cli.EXIT_OK
    assert len(sent) == 1 and "vence em 10 dia(s)" in sent[0]


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
