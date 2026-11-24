"""One-off helper for the Instagram Login flow (no Facebook Page involved).

Run locally (`stories-token-ig`). It takes the token generated in the Meta app dashboard,
optionally turns it into a ~60-day one, renews it, and prints the Instagram user id to use as
`IG_USER_ID`. Secrets are typed or pasted into the terminal and never written to disk.
"""

from __future__ import annotations

from typing import Any

import requests

BASE_URL = "https://graph.instagram.com"
API_VERSION = "v21.0"


class TokenError(RuntimeError):
    """The Instagram API refused a token request."""


def _get(path: str, **params: str) -> dict[str, Any]:
    try:
        response = requests.get(f"{BASE_URL}/{path}", params=params, timeout=60)
    except requests.RequestException as exc:
        raise TokenError(f"network error: {type(exc).__name__}") from None
    try:
        body: dict[str, Any] = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        raise TokenError(f"HTTP {response.status_code}: {body.get('error', {}).get('message', '')}")
    return body


def exchange_for_long_lived(app_secret: str, short_token: str) -> tuple[str, int]:
    """Return (long-lived token, lifetime in days) for a short-lived token."""
    body = _get(
        "access_token",
        grant_type="ig_exchange_token",
        client_secret=app_secret,
        access_token=short_token,
    )
    return str(body["access_token"]), int(body.get("expires_in", 0)) // 86400


def refresh(token: str) -> tuple[str, int]:
    """Renew a long-lived token for another ~60 days (it must be at least 24 h old)."""
    body = _get("refresh_access_token", grant_type="ig_refresh_token", access_token=token)
    return str(body["access_token"]), int(body.get("expires_in", 0)) // 86400


def whoami(token: str) -> tuple[str, str]:
    """Return (instagram user id, username) of the account the token belongs to."""
    body = _get(f"{API_VERSION}/me", fields="user_id,username", access_token=token)
    return str(body.get("user_id") or body["id"]), str(body.get("username", "?"))


def main() -> int:
    token = input("Token from the Meta app dashboard: ").strip()
    app_secret = input("App Secret (Enter to skip and just renew): ").strip()

    try:
        if app_secret:
            token, days = exchange_for_long_lived(app_secret, token)
            print(f"\nLong-lived token issued (expires in ~{days} days).")
        else:
            token, days = refresh(token)
            print(f"\nToken renewed (expires in ~{days} days).")
    except TokenError as exc:
        print(f"\nCould not extend the token ({exc}); using it as it is.")

    try:
        user_id, username = whoami(token)
    except TokenError as exc:
        print(f"Token rejected: {exc}")
        return 1

    print(f"\n@{username}  ->  IG_USER_ID = {user_id}")
    print("\nIG_ACCESS_TOKEN (paste into GitHub Secrets; do not share):")
    print(token)
    print('\nAlso set the repository VARIABLE IG_API = "instagram" (Settings -> Variables).')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
