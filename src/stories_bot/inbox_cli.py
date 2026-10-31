"""Command-line entry point: receive arts sent to the Telegram bot and schedule them."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Sequence
from pathlib import Path

from .cli import EXIT_BAD_SETUP, EXIT_FAILED, EXIT_OK, resolve_now
from .inbox import Inbox, InboxPaths
from .schedule import ScheduleError, load_schedule
from .telegram import TelegramApi, TelegramError

log = logging.getLogger("stories_bot")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stories-inbox", description="Receive Story arts sent to the Telegram bot."
    )
    parser.add_argument("--schedule", type=Path, default=Path("schedule.json"))
    parser.add_argument("--media-dir", type=Path, default=Path("media"))
    parser.add_argument("--state", type=Path, default=Path("state/posted.json"))
    parser.add_argument("--offset-file", type=Path, default=Path("state/telegram.json"))
    parser.add_argument("--now", help="pretend it is this local time, e.g. 2026-10-09T18:05")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    token, chat_id = (
        os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        os.environ.get("TELEGRAM_CHAT_ID", ""),
    )
    if not token or not chat_id:
        log.info("Telegram is not configured; nothing to receive")
        return EXIT_OK

    try:
        schedule = load_schedule(args.schedule)
    except (OSError, ScheduleError) as exc:
        log.error("Cannot load schedule %s: %s", args.schedule, exc)
        return EXIT_BAD_SETUP

    inbox = Inbox(
        TelegramApi(token),
        chat_id,
        InboxPaths(args.schedule, args.media_dir, args.state, args.offset_file),
        resolve_now(args.now, schedule.timezone),
    )
    try:
        handled, failed = inbox.run()
    except TelegramError as exc:
        log.error("Cannot read Telegram messages: %s", exc)
        return EXIT_FAILED
    log.info("%d Telegram message(s) handled", handled)
    return EXIT_FAILED if failed else EXIT_OK
