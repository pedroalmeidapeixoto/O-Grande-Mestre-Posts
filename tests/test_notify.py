import json
import logging

import pytest
import requests
import responses

from stories_bot.notify import TelegramNotifier

SEND_URL = "https://api.telegram.org/botSECRET-TOKEN/sendMessage"
PHOTO_URL = "https://api.telegram.org/botSECRET-TOKEN/sendPhoto"


def test_from_env_requires_both_values():
    assert TelegramNotifier.from_env({}) is None
    assert TelegramNotifier.from_env({"TELEGRAM_BOT_TOKEN": "t"}) is None
    assert TelegramNotifier.from_env({"TELEGRAM_CHAT_ID": "1"}) is None
    assert TelegramNotifier.from_env({"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"})


@responses.activate
def test_send_posts_the_message_to_the_chat():
    responses.post(SEND_URL, json={"ok": True})
    TelegramNotifier("SECRET-TOKEN", "42").send("hello")

    assert json.loads(responses.calls[0].request.body) == {"chat_id": "42", "text": "hello"}


@responses.activate
def test_http_error_is_logged_without_the_token_and_does_not_raise(caplog):
    responses.post(SEND_URL, status=401, json={"ok": False})
    with caplog.at_level(logging.WARNING, logger="stories_bot"):
        TelegramNotifier("SECRET-TOKEN", "42").send("hello")

    assert "HTTP 401" in caplog.text
    assert "SECRET-TOKEN" not in caplog.text


@responses.activate
@pytest.mark.parametrize("error", [requests.ConnectionError, requests.Timeout])
def test_network_error_is_logged_without_the_token_and_does_not_raise(error, caplog):
    responses.post(SEND_URL, body=error(f"cannot reach {SEND_URL}"))
    with caplog.at_level(logging.WARNING, logger="stories_bot"):
        TelegramNotifier("SECRET-TOKEN", "42").send("hello")

    assert error.__name__ in caplog.text
    assert "SECRET-TOKEN" not in caplog.text


@responses.activate
def test_send_for_group_sends_the_art_first_and_the_text_last(tmp_path):
    art = tmp_path / "menu.jpg"
    art.write_bytes(b"jpg-bytes")
    responses.post(PHOTO_URL, json={"ok": True})
    responses.post(SEND_URL, json={"ok": True})

    TelegramNotifier("SECRET-TOKEN", "42").send_for_group(
        art, "*Cardápio* 🍽️", is_video=False, label="menu.jpg"
    )

    assert [c.request.url for c in responses.calls] == [PHOTO_URL, SEND_URL]
    assert b"jpg-bytes" in responses.calls[0].request.body
    assert b"Para o grupo do WhatsApp" in responses.calls[0].request.body
    assert json.loads(responses.calls[1].request.body)["text"] == "*Cardápio* 🍽️"


@responses.activate
def test_send_for_group_uses_send_video_for_videos(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"mp4")
    responses.post("https://api.telegram.org/botSECRET-TOKEN/sendVideo", json={"ok": True})
    responses.post(SEND_URL, json={"ok": True})

    TelegramNotifier("SECRET-TOKEN", "42").send_for_group(
        video, "texto", is_video=True, label="clip.mp4"
    )

    assert responses.calls[0].request.url.endswith("/sendVideo")


@responses.activate
def test_send_for_group_failure_is_logged_and_does_not_raise(tmp_path, caplog):
    art = tmp_path / "menu.jpg"
    art.write_bytes(b"jpg")
    responses.post(PHOTO_URL, status=400, json={"ok": False, "description": "bad"})
    with caplog.at_level(logging.WARNING, logger="stories_bot"):
        TelegramNotifier("SECRET-TOKEN", "42").send_for_group(
            art, "texto", is_video=False, label="menu.jpg"
        )

    assert len(responses.calls) == 1  # the text is not sent without its art
    assert "HTTP 400" in caplog.text and "SECRET-TOKEN" not in caplog.text


def test_send_for_group_with_a_missing_file_does_not_raise(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="stories_bot"):
        TelegramNotifier("SECRET-TOKEN", "42").send_for_group(
            tmp_path / "gone.jpg", "texto", is_video=False, label="gone.jpg"
        )
    assert "failed" in caplog.text
