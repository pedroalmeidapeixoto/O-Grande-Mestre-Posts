"""Command-line entry point: publish whichever Stories are due right now."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import ConfigError, Settings, media_url
from .instagram import InstagramClient, InstagramError
from .schedule import ScheduleError, due_stories, load_schedule
from .state import load_posted, record_post

log = logging.getLogger("stories_bot")

EXIT_OK, EXIT_FAILED, EXIT_BAD_SETUP = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stories-bot", description="Publish scheduled Instagram Stories."
    )
    parser.add_argument("--schedule", type=Path, default=Path("schedule.json"))
    parser.add_argument("--media-dir", type=Path, default=Path("media"))
    parser.add_argument("--state", type=Path, default=Path("state/posted.json"))
    parser.add_argument("--dry-run", action="store_true", help="show what would be published")
    parser.add_argument("--now", help="pretend it is this local time, e.g. 2026-10-09T18:05")
    return parser


def _resolve_now(value: str | None, tz: ZoneInfo) -> datetime:
    if value:
        return datetime.fromisoformat(value).replace(tzinfo=tz)
    return datetime.now(tz)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        schedule = load_schedule(args.schedule)
    except (OSError, ScheduleError) as exc:
        log.error("Cannot load schedule %s: %s", args.schedule, exc)
        return EXIT_BAD_SETUP

    now = _resolve_now(args.now, schedule.timezone)
    due = due_stories(schedule, now, load_posted(args.state))
    log.info("%s: %d Story(ies) due", now.strftime("%Y-%m-%d %H:%M"), len(due))

    settings: Settings | None = None
    client: InstagramClient | None = None
    failures = 0

    for item in due:
        path = args.media_dir / item.slot.file
        if not path.is_file():
            log.error("Media file not found: %s", path)
            failures += 1
            continue
        if args.dry_run:
            log.info("[dry-run] would publish %s", item.slot.file)
            continue

        try:
            if client is None:  # config is only required once something must be published
                settings = Settings.from_env()
                client = InstagramClient(settings.ig_user_id, settings.ig_access_token)
            assert settings is not None
            url = media_url(settings.media_base_url, path.name)
            media_id = client.publish_story(url, is_video=item.slot.is_video)
        except ConfigError as exc:
            log.error("Configuration error: %s", exc)
            return EXIT_BAD_SETUP
        except InstagramError as exc:
            log.error("Failed to publish %s: %s", item.slot.file, exc)
            failures += 1
            continue

        record_post(args.state, item.key, media_id, now)
        log.info("Published %s (media id %s)", item.slot.file, media_id)

    return EXIT_FAILED if failures else EXIT_OK
