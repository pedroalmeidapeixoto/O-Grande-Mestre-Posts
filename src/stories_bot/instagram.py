"""Minimal client for publishing Stories through the Instagram Graph API.

Publishing is a three-step flow: create a media container, wait until Meta finishes
processing it, then publish the container.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

GRAPH_URL = "https://graph.facebook.com/v21.0"
REQUEST_TIMEOUT = 60


class InstagramError(RuntimeError):
    """The Graph API rejected a request or the container never became ready.

    Messages never include the request URL, so the access token cannot leak into logs.
    """


class InstagramClient:
    def __init__(
        self,
        user_id: str,
        access_token: str,
        *,
        session: requests.Session | None = None,
        poll_interval: float = 10.0,
        max_polls: int = 30,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._user_id = user_id
        self._token = access_token
        self._session = session or requests.Session()
        self._poll_interval = poll_interval
        self._max_polls = max_polls
        self._sleep = sleep

    def publish_story(self, media_url: str, *, is_video: bool) -> str:
        """Publish a Story from a public URL and return the resulting media id."""
        container = self._create_container(media_url, is_video=is_video)
        self._wait_until_ready(container)
        return self._publish(container)

    def _create_container(self, media_url: str, *, is_video: bool) -> str:
        field = "video_url" if is_video else "image_url"
        body = self._call(
            "POST", f"{self._user_id}/media", {"media_type": "STORIES", field: media_url}
        )
        return str(body["id"])

    def _wait_until_ready(self, container: str) -> None:
        for _ in range(self._max_polls):
            body = self._call("GET", container, {"fields": "status_code"})
            status = body.get("status_code")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise InstagramError(f"container {container} failed with status {status}")
            self._sleep(self._poll_interval)
        raise InstagramError(f"container {container} was not ready after {self._max_polls} checks")

    def _publish(self, container: str) -> str:
        body = self._call("POST", f"{self._user_id}/media_publish", {"creation_id": container})
        return str(body["id"])

    def _call(self, method: str, path: str, params: dict[str, str]) -> dict[str, Any]:
        payload = {**params, "access_token": self._token}
        kwargs: dict[str, Any] = {"params": payload} if method == "GET" else {"data": payload}
        try:
            response = self._session.request(
                method, f"{GRAPH_URL}/{path}", timeout=REQUEST_TIMEOUT, **kwargs
            )
        except requests.RequestException as exc:
            raise InstagramError(f"network error: {type(exc).__name__}") from None

        try:
            body: dict[str, Any] = response.json()
        except ValueError:
            body = {}
        if not response.ok:
            message = body.get("error", {}).get("message", "no details")
            raise InstagramError(f"HTTP {response.status_code}: {message}")
        return body
