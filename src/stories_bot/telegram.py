"""Thin Telegram Bot API client shared by notifications and the inbox."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import requests

API_URL = "https://api.telegram.org"
REQUEST_TIMEOUT = 30


class TelegramError(RuntimeError):
    """A Bot API call failed.

    Messages never include the request URL, because the bot token is part of it.
    """


class TelegramApi:
    def __init__(self, bot_token: str, *, session: requests.Session | None = None) -> None:
        self._token = bot_token
        self._session = session or requests.Session()

    def call(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        """Call a Bot API method and return its `result`."""
        try:
            response = self._session.post(
                f"{API_URL}/bot{self._token}/{method}",
                json=dict(params or {}),
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise TelegramError(f"network error: {type(exc).__name__}") from None

        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            body = {}
        if not response.ok or not body.get("ok"):
            raise TelegramError(
                f"HTTP {response.status_code}: {body.get('description', 'no details')}"
            )
        return body.get("result")

    def download(self, file_path: str) -> bytes:
        """Download a file previously resolved with `getFile`."""
        try:
            response = self._session.get(
                f"{API_URL}/file/bot{self._token}/{file_path}", timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            raise TelegramError(f"network error: {type(exc).__name__}") from None
        if not response.ok:
            raise TelegramError(f"HTTP {response.status_code} while downloading the file")
        return response.content
