"""Persistent record of published Stories (keeps the bot idempotent across runs)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def load_posted(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data: dict[str, dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return data


def record_post(path: Path, key: str, media_id: str, at: datetime) -> None:
    """Add one entry and write the file atomically (a crash never leaves it half-written)."""
    posted = load_posted(path)
    posted[key] = {"media_id": media_id, "posted_at": at.isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(posted, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
