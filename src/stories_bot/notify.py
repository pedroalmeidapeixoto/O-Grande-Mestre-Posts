"""Optional Telegram notifications, so nobody has to open Actions to know a Story went out."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path

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

    def send_for_group(self, path: Path, caption: str, *, is_video: bool, label: str) -> None:
        """Hand over a published art plus its ready-made text, to be forwarded to a
        WhatsApp group by hand. The art goes first and the text last, as its own message,
        so it is the easiest thing to long-press and copy.
        """
        method, field = ("sendVideo", "video") if is_video else ("sendPhoto", "photo")
        try:
            with path.open("rb") as content:
                self._api.upload(
                    method,
                    {"chat_id": self._chat_id, "caption": f"📲 Para o grupo do WhatsApp — {label}"},
                    field,
                    path.name,
                    content,
                )
            self._api.call("sendMessage", {"chat_id": self._chat_id, "text": caption})
        except (TelegramError, OSError) as exc:
            log.warning("Sending the art for the group failed: %s", exc)
