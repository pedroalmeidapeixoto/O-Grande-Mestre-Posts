"""Optional Telegram notifications, so nobody has to open Actions to know a Story went out."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from .telegram import TelegramApi, TelegramError

log = logging.getLogger("stories_bot")

WHATSAPP_SHARE_URL = "https://wa.me/?text="
MAX_BUTTON_URL_LENGTH = 2000  # Telegram refuses inline-button links longer than 2048


def whatsapp_share_url(text: str) -> str | None:
    """A link that opens WhatsApp with `text` filled in, ready to be sent to any chat.

    Returns None when the text is too long to fit in a Telegram button.
    """
    url = WHATSAPP_SHARE_URL + quote(text, safe="")
    return url if len(url) <= MAX_BUTTON_URL_LENGTH else None


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
        with a button that opens WhatsApp already filled in with that text (pick the group,
        send), so only the art needs to be attached.
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
            message: dict[str, Any] = {"chat_id": self._chat_id, "text": caption}
            share = whatsapp_share_url(caption)
            if share:
                message["reply_markup"] = {
                    "inline_keyboard": [[{"text": "📲 Abrir no WhatsApp", "url": share}]]
                }
            else:
                log.warning("The text for %s is too long for a WhatsApp button", label)
            self._api.call("sendMessage", message)
        except (TelegramError, OSError) as exc:
            log.warning("Sending the art for the group failed: %s", exc)
