"""One-off helper: exchange a short-lived token for a ~60-day one and find the IG user id.

Run locally (`stories-token`). Secrets are typed or pasted into the terminal and are never
written to disk; copy the printed values into your GitHub repository secrets, then clear
the terminal. (Input is visible because `getpass` ignores paste on Windows consoles.)
"""

from __future__ import annotations

from typing import Any

import requests

GRAPH_URL = "https://graph.facebook.com/v21.0"


def _get(path: str, **params: str) -> dict[str, Any]:
    response = requests.get(f"{GRAPH_URL}/{path}", params=params, timeout=60)
    if not response.ok:
        raise SystemExit(f"Meta API error: {response.text}")
    body: dict[str, Any] = response.json()
    return body


def exchange_for_long_lived(app_id: str, app_secret: str, short_token: str) -> tuple[str, int]:
    """Return (long-lived token, lifetime in days)."""
    body = _get(
        "oauth/access_token",
        grant_type="fb_exchange_token",
        client_id=app_id,
        client_secret=app_secret,
        fb_exchange_token=short_token,
    )
    return str(body["access_token"]), int(body.get("expires_in", 0)) // 86400


def find_instagram_accounts(app_id: str, app_secret: str, token: str) -> list[tuple[str, str]]:
    """Return [(label, instagram_user_id)] for the accounts this token may publish to.

    Pages managed through a business portfolio may be missing from `me/accounts`, so the
    ids granted to the token (granular scopes) are used as the source of truth.
    """
    info = _get("debug_token", input_token=token, access_token=f"{app_id}|{app_secret}")
    granted = {s["scope"]: s.get("target_ids", []) for s in info["data"].get("granular_scopes", [])}
    ig_ids: list[str] = granted.get("instagram_content_publish") or granted.get(
        "instagram_basic", []
    )

    accounts = []
    for ig_id in ig_ids:
        profile = _get(ig_id, access_token=token, fields="username")
        accounts.append((f"@{profile.get('username', '?')}", ig_id))
    return accounts


def main() -> int:
    app_id = input("App ID: ").strip()
    app_secret = input("App Secret: ").strip()
    short_token = input("Short-lived token (from the Graph API Explorer): ").strip()

    token, days = exchange_for_long_lived(app_id, app_secret, short_token)
    print(f"\nLong-lived token issued (expires in ~{days} days).")

    accounts = find_instagram_accounts(app_id, app_secret, token)
    if not accounts:
        print("No Instagram account is authorized for this token. Re-generate it and select one.")
        return 1

    print("\nInstagram accounts:")
    for label, ig_id in accounts:
        print(f"  {label}  ->  IG_USER_ID = {ig_id}")
    print("\nIG_ACCESS_TOKEN (paste into GitHub Secrets; do not share):")
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
