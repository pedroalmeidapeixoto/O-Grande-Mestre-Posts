"""Command-line entry point: publish whichever Stories are due right now."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import ConfigError, Settings, media_url
from .instagram import InstagramClient, InstagramError
from .notify import TelegramNotifier
from .schedule import DueStory, ScheduleError, due_stories, load_schedule
from .state import MAX_ATTEMPTS, load_attempts, load_posted, record_failure, record_post
from .token_expiry import reminder_due

log = logging.getLogger("stories_bot")

EXIT_OK, EXIT_FAILED, EXIT_BAD_SETUP = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stories-bot", description="Publish scheduled Instagram Stories."
    )
    parser.add_argument("--schedule", type=Path, default=Path("schedule.json"))
    parser.add_argument("--media-dir", type=Path, default=Path("media"))
    parser.add_argument("--state", type=Path, default=Path("state/posted.json"))
    parser.add_argument("--attempts", type=Path, default=Path("state/attempts.json"))
    parser.add_argument("--reminders", type=Path, default=Path("state/reminders.json"))
    parser.add_argument("--dry-run", action="store_true", help="show what would be published")
    parser.add_argument("--now", help="pretend it is this local time, e.g. 2026-10-09T18:05")
    return parser


def resolve_now(value: str | None, tz: ZoneInfo) -> datetime:
    if value:
        return datetime.fromisoformat(value).replace(tzinfo=tz)
    return datetime.now(tz)


def _notify(notifier: TelegramNotifier | None, text: str) -> None:
    if notifier is not None:
        notifier.send(text)


def _failure_note(count: int) -> str:
    if count >= MAX_ATTEMPTS:
        return f" Desisti depois de {MAX_ATTEMPTS} tentativas."
    return f" Tentativa {count} de {MAX_ATTEMPTS}; tento de novo na próxima rodada."


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        schedule = load_schedule(args.schedule)
    except (OSError, ScheduleError) as exc:
        log.error("Cannot load schedule %s: %s", args.schedule, exc)
        return EXIT_BAD_SETUP

    now = resolve_now(args.now, schedule.timezone)
    notifier = None if args.dry_run else TelegramNotifier.from_env()
    if notifier is not None:
        reminder = reminder_due(os.environ, now, args.reminders)
        if reminder:
            notifier.send(reminder)

    attempts = load_attempts(args.attempts)
    due: list[DueStory] = []
    for story in due_stories(schedule, now, load_posted(args.state)):
        if attempts.get(story.key, {}).get("count", 0) >= MAX_ATTEMPTS:
            log.warning("Giving up on %s after %d failed attempts", story.slot.file, MAX_ATTEMPTS)
        else:
            due.append(story)
    log.info("%s: %d Story(ies) due", now.strftime("%Y-%m-%d %H:%M"), len(due))

    settings: Settings | None = None
    client: InstagramClient | None = None
    failures = 0

    for item in due:
        path = args.media_dir / item.slot.file
        if not path.is_file():
            log.error("Media file not found: %s", path)
            if not args.dry_run:
                count = record_failure(args.attempts, item.key, "media file not found", now)
                _notify(
                    notifier,
                    f"❌ Story não publicado: arquivo {item.slot.file} não encontrado."
                    + _failure_note(count),
                )
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
            _notify(notifier, f"❌ Story não publicado: configuração incompleta ({exc}).")
            return EXIT_BAD_SETUP
        except InstagramError as exc:
            log.error("Failed to publish %s: %s", item.slot.file, exc)
            if exc.is_auth_error:  # every Story would fail the same way: do not burn attempts
                _notify(
                    notifier,
                    f"❌ O Instagram recusou o token ({exc}). "
                    "Gere um novo com `stories-token` e atualize o secret IG_ACCESS_TOKEN.",
                )
                return EXIT_BAD_SETUP
            count = record_failure(args.attempts, item.key, str(exc), now)
            _notify(
                notifier, f"❌ Falha ao publicar {item.slot.file}: {exc}." + _failure_note(count)
            )
            failures += 1
            continue

        record_post(args.state, item.key, media_id, now)
        log.info("Published %s (media id %s)", item.slot.file, media_id)
        _notify(notifier, f"✅ Story publicado: {item.slot.file} ({now:%d/%m %H:%M})")

    return EXIT_FAILED if failures else EXIT_OK
