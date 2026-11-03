"""Housekeeping: drop old one-off Stories, their arts and stale records.

`schedule.json`, `media/` and the state files would otherwise grow with every Story. Nothing
that is still pending, or recent enough to be useful, is ever removed.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from .cli import EXIT_BAD_SETUP, EXIT_OK, resolve_now
from .schedule import ScheduleError, load_schedule, prune_one_offs
from .state import prune_records

log = logging.getLogger("stories_bot")

ONE_OFF_KEEP_DAYS = 2  # a one-off stays in the schedule this many days after its date
POSTED_KEEP_DAYS = 30
SHORT_KEEP_DAYS = 7  # failed attempts and missed-Story reports


def tidy(
    schedule_path: Path,
    media_dir: Path,
    posted_path: Path,
    attempts_path: Path,
    missed_path: Path,
    now: datetime,
) -> dict[str, int]:
    """Clean up and return how many items of each kind were removed."""
    removed_files = prune_one_offs(schedule_path, now.date() - timedelta(days=ONE_OFF_KEEP_DAYS))

    still_used = {slot.file for slot in load_schedule(schedule_path).slots}
    deleted_arts = 0
    for name in set(removed_files) - still_used:  # never touch an art another Story still uses
        art = media_dir / name
        if art.is_file():
            art.unlink()
            deleted_arts += 1

    short = now - timedelta(days=SHORT_KEEP_DAYS)
    return {
        "stories": len(removed_files),
        "arts": deleted_arts,
        "posted": prune_records(
            posted_path, now - timedelta(days=POSTED_KEEP_DAYS), lambda v: v["posted_at"]
        ),
        "attempts": prune_records(attempts_path, short, lambda v: v["last_attempt"]),
        "missed": prune_records(missed_path, short, lambda v: v),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stories-tidy", description="Remove old one-off Stories, their arts and stale records."
    )
    parser.add_argument("--schedule", type=Path, default=Path("schedule.json"))
    parser.add_argument("--media-dir", type=Path, default=Path("media"))
    parser.add_argument("--state", type=Path, default=Path("state/posted.json"))
    parser.add_argument("--attempts", type=Path, default=Path("state/attempts.json"))
    parser.add_argument("--missed", type=Path, default=Path("state/missed.json"))
    parser.add_argument("--now", help="pretend it is this local time, e.g. 2026-10-09T18:05")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        schedule = load_schedule(args.schedule)
    except (OSError, ScheduleError) as exc:
        log.error("Cannot load schedule %s: %s", args.schedule, exc)
        return EXIT_BAD_SETUP

    now = resolve_now(args.now, schedule.timezone)
    removed = tidy(args.schedule, args.media_dir, args.state, args.attempts, args.missed, now)
    if any(removed.values()):
        log.info("Tidied up: %s", ", ".join(f"{n} {kind}" for kind, n in removed.items() if n))
    return EXIT_OK
