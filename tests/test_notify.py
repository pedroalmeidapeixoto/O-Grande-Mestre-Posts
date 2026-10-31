import json
import logging

import pytest
import requests
import responses

from stories_bot.notify import TelegramNotifier

SEND_URL = "https://api.telegram.org/botSECRET-TOKEN/sendMessage"


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
