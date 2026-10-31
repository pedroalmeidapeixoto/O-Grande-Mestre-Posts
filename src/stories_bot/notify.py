"""Optional Telegram notifications, so nobody has to open Actions to know a Story went out."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

import requests

log = logging.getLogger("stories_bot")

API_URL = "https://api.telegram.org"
REQUEST_TIMEOUT = 15


class TelegramNotifier:
    """Sends short messages through a Telegram bot. It never raises: a notification that
    cannot be delivered must not make a successful publish look like a failure.

    Log lines only carry the exception type or status code, never the request URL, because
    the bot token is part of that URL.
    """

    def __init__(
        self, bot_token: str, chat_id: str, *, session: requests.Session | None = None
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._session = session or requests.Session()

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
            response = self._session.post(
                f"{API_URL}/bot{self._token}/sendMessage",
                data={"chat_id": self._chat_id, "text": text},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            log.warning("Telegram notification failed: %s", type(exc).__name__)
            return
        if not response.ok:
            log.warning("Telegram notification failed: HTTP %s", response.status_code)
