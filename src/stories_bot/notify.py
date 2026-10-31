"""Optional Telegram notifications, so nobody has to open Actions to know a Story went out."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

import requests

from .telegram import TelegramApi, TelegramError

log = logging.getLogger("stories_bot")


class TelegramNotifier:
    """Sends short messages through a Telegram bot. It never raises: a notification that
    cannot be delivered must not make a successful publish look like a failure.
    """

    def __init__(
        self, bot_token: str, chat_id: str, *, session: requests.Session | None = None
    ) -> None:
        self._api = TelegramApi(bot_token, session=session)
        self._chat_id = chat_id

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> TelegramNotifier | None:
        """Return a notifier, or None when the Telegram secrets are not configured."""
        env = os.environ if environ is None else environ
        token, chat_id = env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return None
        return cls(token, chat_id)

    def send(self, text: str) -> None:
        try:
            self._api.call("sendMessage", {"chat_id": self._chat_id, "text": text})
        except TelegramError as exc:
            log.warning("Telegram notification failed: %s", exc)
