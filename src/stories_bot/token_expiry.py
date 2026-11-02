"""Reminder that the long-lived Instagram token is about to expire.

The token lasts about 60 days and cannot be renewed without a person. The date it was issued
is kept in the repository variable `IG_TOKEN_ISSUED` (YYYY-MM-DD), so no extra secret is needed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path

from .state import write_json

log = logging.getLogger("stories_bot")

TOKEN_LIFETIME_DAYS = 60
WARN_DAYS = 10


def days_left(issued: date, today: date) -> int:
    return TOKEN_LIFETIME_DAYS - (today - issued).days


def _message(left: int) -> str:
    how = (
        "Gere um novo com `stories-token` e atualize o secret IG_ACCESS_TOKEN "
        "e a variável IG_TOKEN_ISSUED."
    )
    if left > 0:
        return f"⚠️ O token do Instagram vence em {left} dia(s). {how}"
    return f"❌ O token do Instagram venceu (há {-left} dia(s)). {how}"


def reminder_due(environ: Mapping[str, str], now: datetime, state_path: Path) -> str | None:
    """The reminder text, at most once a day and only inside the warning period.

    Returns None when the variable is unset or invalid, or there is nothing to say today.
    """
    raw = environ.get("IG_TOKEN_ISSUED", "").strip()
    if not raw:
        return None
    try:
        issued = date.fromisoformat(raw)
    except ValueError:
        log.warning("IG_TOKEN_ISSUED must be YYYY-MM-DD, got %r; no expiry reminder", raw)
        return None

    today = now.date()
    left = days_left(issued, today)
    if left > WARN_DAYS:
        return None

    sent: dict[str, str] = {}
    if state_path.exists():
        sent = json.loads(state_path.read_text(encoding="utf-8"))
    if sent.get("token_expiry") == today.isoformat():
        return None
    write_json(state_path, {**sent, "token_expiry": today.isoformat()})
    return _message(left)
