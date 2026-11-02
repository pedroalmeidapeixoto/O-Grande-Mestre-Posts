import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stories_bot import inbox_cli
from stories_bot.inbox import Inbox, InboxPaths, parse_when
from stories_bot.state import load_offset
from stories_bot.telegram import TelegramError

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=TZ)  # a Saturday
ME = 777


def png(width: int, height: int) -> bytes:
    header = b"\x00\x00\x00\rIHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big")
    return b"\x89PNG\r\n\x1a\n" + header + b"\x08\x06\x00\x00\x00"


STORY_ART = png(1080, 1920)


class FakeApi:
    """Stands in for TelegramApi: serves queued updates and records what the bot says."""

    def __init__(self, updates=(), files=None):
        self.updates = list(updates)
        self.files = files or {}
        self.sent: list[str] = []
        self.download_error: str | None = None
        self.too_big: set[str] = set()
        self.last_offset = None

    def call(self, method, params=None):
        if method == "getUpdates":
            self.last_offset = params.get("offset")
            return [u for u in self.updates if u["update_id"] >= (params.get("offset") or 0)]
        if method == "getFile":
            if params["file_id"] in self.too_big:
                raise TelegramError("HTTP 400: Bad Request: file is too big")
            return {"file_path": f"documents/{params['file_id']}"}
        if method == "sendMessage":
            self.sent.append(params["text"])
            return {}
        raise AssertionError(method)

    def download(self, file_path):
        if self.download_error:
            raise TelegramError(self.download_error)
        return self.files[file_path.rsplit("/", 1)[-1]]


def message(update_id, *, chat=ME, kind="private", **fields):
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": chat, "type": kind},
            **fields,
        },
    }


def document(update_id, file_id="f1", name="feriado.jpg", caption=None, mime="image/jpeg", **kw):
    fields = {"document": {"file_id": file_id, "file_name": name, "mime_type": mime}}
    if caption is not None:
        fields["caption"] = caption
    return message(update_id, **fields, **kw)


def text(update_id, body, **kw):
    return message(update_id, text=body, **kw)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "schedule.json").write_text(
        json.dumps({"timezone": "America/Sao_Paulo", "window_minutes": 60, "stories": []})
    )
    return InboxPaths(
        schedule=tmp_path / "schedule.json",
        media_dir=tmp_path / "media",
        posted=tmp_path / "state" / "posted.json",
        offset=tmp_path / "state" / "telegram.json",
    )


def run(api, project, now=NOW):
    return Inbox(api, str(ME), project, now).run()


def stories(project):
    return json.loads(project.schedule.read_text())["stories"]


# -- caption parsing ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("caption", "expected"),
    [
        ("hoje 18:30", ("2026-10-31", "18:30")),
        ("HOJE 18h30", ("2026-10-31", "18:30")),
        ("amanhã 12h", ("2026-11-01", "12:00")),
        ("amanha 9:05", ("2026-11-01", "09:05")),
        ("18:30", ("2026-10-31", "18:30")),
        ("15/11 10:00", ("2026-11-15", "10:00")),
        ("15/11/2027 10:00", ("2027-11-15", "10:00")),
        ("2026-12-25 10h", ("2026-12-25", "10:00")),
        ("", ("2026-10-31", "12:00")),  # no caption: as soon as possible
        (None, ("2026-10-31", "12:00")),
    ],
)
def test_parse_when(caption, expected):
    day, at = parse_when(caption, NOW)
    assert (day.isoformat(), f"{at:%H:%M}") == expected


@pytest.mark.parametrize(
    "caption",
    ["quando der", "hoje", "hoje 25:00", "hoje 18:75", "31/02 10:00", "a b c", "ontem 10h"],
)
def test_unreadable_captions_are_rejected(caption):
    assert parse_when(caption, NOW) is None


# -- receiving arts ----------------------------------------------------------------------


def test_art_with_caption_is_saved_and_scheduled(project):
    api = FakeApi([document(10, caption="hoje 18:30")], {"f1": STORY_ART})

    assert run(api, project) == (1, False)

    saved = stories(project)
    assert saved == [{"date": "2026-10-31", "time": "18:30", "file": "20261031-feriado-10.jpg"}]
    assert (project.media_dir / "20261031-feriado-10.jpg").read_bytes() == STORY_ART
    assert "Agendado para 31/10/2026 às 18:30" in api.sent[0]
    assert load_offset(project.offset) == 11


def test_art_without_caption_goes_out_on_the_next_run(project):
    api = FakeApi([document(10)], {"f1": STORY_ART})
    run(api, project)

    assert stories(project)[0]["time"] == "12:00"
    assert "próxima rodada" in api.sent[0]


def test_unreadable_caption_asks_again_and_saves_nothing(project):
    api = FakeApi([document(10, caption="quando der")], {"f1": STORY_ART})
    run(api, project)

    assert stories(project) == []
    assert not project.media_dir.exists()
    assert "Não entendi" in api.sent[0]
    assert load_offset(project.offset) == 11  # consumed, the user simply resends


def test_time_already_out_of_the_window_is_rejected(project):
    api = FakeApi([document(10, caption="hoje 09:00")], {"f1": STORY_ART})  # window is 60 min
    run(api, project)

    assert stories(project) == []
    assert "já passou" in api.sent[0]


def test_non_story_ratio_and_compressed_photo_get_warnings(project):
    photo = message(
        10,
        photo=[
            {"file_id": "small", "width": 90, "height": 160},
            {"file_id": "big", "width": 720, "height": 960},
        ],
        caption="hoje 18:30",
    )
    api = FakeApi([photo], {"big": png(720, 960)})
    run(api, project)

    assert len(stories(project)) == 1
    assert "foto" in api.sent[0] and "720×960" in api.sent[0]


def test_unsupported_format_is_refused(project):
    api = FakeApi([document(10, name="notes.pdf", mime="application/pdf")])
    run(api, project)

    assert stories(project) == []
    assert "Formato não suportado" in api.sent[0]


def test_format_is_taken_from_mime_type_when_the_name_has_none(project):
    api = FakeApi([document(10, name="", mime="video/mp4", caption="hoje 18:30")], {"f1": b"mp4"})
    run(api, project)

    assert stories(project)[0]["file"] == "20261031-arte-10.mp4"


def test_file_too_big_is_reported_and_consumed(project):
    api = FakeApi([document(10, caption="hoje 18:30")])
    api.too_big.add("f1")
    assert run(api, project) == (1, False)

    assert "20 MB" in api.sent[0]
    assert load_offset(project.offset) == 11


def test_download_failure_stops_and_retries_on_the_next_run(project):
    api = FakeApi([document(10, caption="hoje 18:30"), text(11, "/fila")], {"f1": STORY_ART})
    api.download_error = "network error: ConnectionError"

    assert run(api, project) == (0, True)
    assert load_offset(project.offset) is None  # nothing consumed

    api.download_error = None
    assert run(api, project) == (2, False)
    assert len(stories(project)) == 1


# -- security ----------------------------------------------------------------------------


def test_other_people_are_ignored_without_a_reply(project):
    api = FakeApi(
        [document(10, chat=999, caption="hoje 18:30"), text(11, "/fila", chat=999)],
        {"f1": STORY_ART},
    )
    assert run(api, project) == (2, False)

    assert stories(project) == []
    assert not project.media_dir.exists()
    assert api.sent == []


def test_group_chats_are_ignored_even_with_the_right_id(project):
    api = FakeApi([document(10, kind="group", caption="hoje 18:30")], {"f1": STORY_ART})
    run(api, project)

    assert stories(project) == []
    assert api.sent == []


# -- commands ----------------------------------------------------------------------------


def test_offset_is_sent_on_the_next_poll(project):
    api = FakeApi([text(10, "/ajuda")])
    run(api, project)
    run(api, project)

    assert api.last_offset == 11
    assert len(api.sent) == 1  # the same message is not handled twice


def test_start_and_unknown_text_show_help(project):
    api = FakeApi([text(10, "/start"), text(11, "bom dia")])
    run(api, project)

    assert api.sent[0].startswith("Olá!") and "Como usar" in api.sent[0]
    assert api.sent[1].startswith("Como usar")


def test_fila_lists_pending_one_offs_and_recurring_stories(project):
    project.schedule.write_text(
        json.dumps(
            {
                "timezone": "America/Sao_Paulo",
                "window_minutes": 60,
                "stories": [
                    {"date": "2026-11-15", "time": "10:00", "file": "later.jpg"},
                    {"date": "2026-10-31", "time": "18:30", "file": "today.jpg"},
                    {"date": "2026-10-30", "time": "10:00", "file": "old.jpg"},  # past
                    {"date": "2026-10-31", "time": "11:30", "file": "done.jpg"},  # posted
                    {"days": ["sat", "fri"], "time": "18:00", "file": "weekly.jpg"},
                ],
            }
        )
    )
    project.posted.parent.mkdir()
    project.posted.write_text(json.dumps({"2026-10-31|11:30|done.jpg": {}}))

    api = FakeApi([text(10, "/fila")])
    run(api, project)

    assert api.sent[0] == (
        "Agendados:\n"
        "2. 31/10 18:30 — today.jpg\n"
        "1. 15/11 10:00 — later.jpg\n"
        "5. toda semana (fri, sat) 18:00 — weekly.jpg"
    )


def test_fila_with_nothing_scheduled(project):
    api = FakeApi([text(10, "/fila@ograndemestrerestaurante_bot")])
    run(api, project)
    assert api.sent == ["Nada agendado."]


def schedule_with(project, stories, media=()):
    project.schedule.write_text(
        json.dumps({"timezone": "America/Sao_Paulo", "window_minutes": 60, "stories": stories})
    )
    project.media_dir.mkdir(exist_ok=True)
    for name in media:
        (project.media_dir / name).write_bytes(b"art")


def test_cancel_removes_the_story_and_its_art(project):
    schedule_with(
        project,
        [
            {"date": "2026-10-31", "time": "18:30", "file": "a.jpg"},
            {"date": "2026-11-01", "time": "10:00", "file": "b.jpg"},
        ],
        media=["a.jpg", "b.jpg"],
    )
    api = FakeApi([text(10, "/cancelar 1")])
    run(api, project)

    assert [s["file"] for s in stories(project)] == ["b.jpg"]
    assert not (project.media_dir / "a.jpg").exists()
    assert (project.media_dir / "b.jpg").exists()
    assert api.sent == ["🗑️ Cancelei 31/10 18:30 — a.jpg."]


def test_numbers_do_not_shift_when_earlier_stories_are_no_longer_listed(project):
    schedule_with(
        project,
        [
            {"date": "2026-10-30", "time": "10:00", "file": "old.jpg"},  # past: not listed
            {"date": "2026-10-31", "time": "18:30", "file": "today.jpg"},
        ],
        media=["old.jpg", "today.jpg"],
    )
    api = FakeApi([text(10, "/fila"), text(11, "/cancelar 2")])
    run(api, project)

    assert api.sent[0] == "Agendados:\n2. 31/10 18:30 — today.jpg"
    assert [s["file"] for s in stories(project)] == ["old.jpg"]
    assert (project.media_dir / "old.jpg").exists()


def test_cancel_keeps_an_art_that_another_story_still_uses(project):
    schedule_with(
        project,
        [
            {"days": ["sat"], "time": "18:00", "file": "weekly.jpg"},
            {"date": "2026-11-07", "time": "18:00", "file": "weekly.jpg"},
        ],
        media=["weekly.jpg"],
    )
    api = FakeApi([text(10, "/cancelar 2")])
    run(api, project)

    assert len(stories(project)) == 1
    assert (project.media_dir / "weekly.jpg").exists()


def test_cancel_works_for_recurring_stories_and_with_the_bot_suffix(project):
    schedule_with(
        project, [{"days": ["sat", "fri"], "time": "18:00", "file": "weekly.jpg"}], ["weekly.jpg"]
    )
    api = FakeApi([text(10, "/cancelar@ograndemestrerestaurante_bot 1")])
    run(api, project)

    assert stories(project) == []
    assert api.sent == ["🗑️ Cancelei toda semana (fri, sat) 18:00 — weekly.jpg."]


@pytest.mark.parametrize("command", ["/cancelar", "/cancelar abc", "/cancelar 0", "/cancelar -1"])
def test_cancel_needs_a_number_from_the_list(project, command):
    schedule_with(project, [{"date": "2026-10-31", "time": "18:30", "file": "a.jpg"}], ["a.jpg"])
    api = FakeApi([text(10, command)])
    run(api, project)

    assert len(stories(project)) == 1
    assert "Use /cancelar N" in api.sent[0]


def test_cancel_refuses_numbers_that_are_not_pending(project):
    schedule_with(
        project,
        [
            {"date": "2026-10-30", "time": "10:00", "file": "past.jpg"},
            {"date": "2026-10-31", "time": "11:30", "file": "done.jpg"},
        ],
        media=["past.jpg", "done.jpg"],
    )
    project.posted.parent.mkdir()
    project.posted.write_text(json.dumps({"2026-10-31|11:30|done.jpg": {}}))
    api = FakeApi([text(10, "/cancelar 1"), text(11, "/cancelar 2"), text(12, "/cancelar 9")])
    run(api, project)

    assert len(stories(project)) == 2
    assert all("não está na fila" in reply for reply in api.sent)


def test_a_stranger_cannot_cancel(project):
    schedule_with(project, [{"date": "2026-10-31", "time": "18:30", "file": "a.jpg"}], ["a.jpg"])
    api = FakeApi([text(10, "/cancelar 1", chat=999)])
    run(api, project)

    assert len(stories(project)) == 1
    assert api.sent == []


def test_a_failed_reply_does_not_break_the_run(project):
    api = FakeApi([text(10, "/ajuda")])

    def broken(method, params=None):
        if method == "getUpdates":
            return api.updates
        raise TelegramError("HTTP 403: Forbidden: bot was blocked by the user")

    api.call = broken
    assert run(api, project) == (1, False)


# -- command line ------------------------------------------------------------------------


def test_cli_is_a_noop_without_telegram_secrets(project, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert inbox_cli.main(["--schedule", str(project.schedule)]) == inbox_cli.EXIT_OK


def test_cli_reports_a_bad_schedule(project, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(ME))
    project.schedule.write_text("{not json")
    assert inbox_cli.main(["--schedule", str(project.schedule)]) == inbox_cli.EXIT_BAD_SETUP


def test_cli_runs_the_inbox(project, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(ME))
    api = FakeApi([document(10, caption="hoje 23:00")], {"f1": STORY_ART})
    monkeypatch.setattr(inbox_cli, "TelegramApi", lambda token: api)

    code = inbox_cli.main(
        [
            "--schedule", str(project.schedule),
            "--media-dir", str(project.media_dir),
            "--state", str(project.posted),
            "--offset-file", str(project.offset),
            "--now", "2026-10-31T12:00",
        ]
    )  # fmt: skip
    assert code == inbox_cli.EXIT_OK
    assert len(stories(project)) == 1


def test_cli_fails_when_telegram_is_unreachable(project, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(ME))

    class Down:
        def call(self, method, params=None):
            raise TelegramError("HTTP 401: Unauthorized")

    monkeypatch.setattr(inbox_cli, "TelegramApi", lambda token: Down())
    assert inbox_cli.main(["--schedule", str(project.schedule)]) == inbox_cli.EXIT_FAILED
