"""Receive Story arts through a private Telegram chat and put them on the schedule.

The bot is polled (`getUpdates`) from the scheduled workflow, so there is no server. Only the
configured chat is obeyed: anyone else who finds the bot is ignored without a reply.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from .media import image_size, is_story_ratio
from .schedule import (
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    WEEKDAYS,
    Slot,
    add_one_off,
    load_schedule,
    remove_story,
)
from .state import load_offset, load_posted, save_offset
from .telegram import TelegramApi, TelegramError

log = logging.getLogger("stories_bot")

MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}

HELP = (
    "Como usar:\n"
    "• Envie a arte do Story como ARQUIVO (clipe de papel → Arquivo), em JPG, PNG, MP4 ou MOV, "
    "no tamanho 1080×1920.\n"
    '• Na legenda, diga quando publicar: "hoje 18:30", "amanhã 12h", "15/11 10:00" ou '
    '"2026-11-15 10:00".\n'
    "• Sem legenda, o Story sai na próxima rodada, em poucos minutos.\n"
    "• /fila mostra o que está agendado, com um número para cada Story.\n"
    "• /cancelar N cancela o Story de número N."
)

BAD_CAPTION = (
    "Não entendi o horário da legenda. Use, por exemplo, "
    '"hoje 18:30", "amanhã 12h", "15/11 10:00" ou "2026-11-15 10:00". '
    "Mande a arte de novo com a legenda corrigida."
)

_TIME = re.compile(r"(\d{1,2})(?::(\d{2})|h(\d{2})?)")
_DAY_MONTH = re.compile(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?")


class UnsupportedMedia(ValueError):
    """The attachment is not a JPG, PNG, MP4 or MOV."""


@dataclass(frozen=True)
class Attachment:
    file_id: str
    stem: str
    suffix: str
    compressed_photo: bool = False


@dataclass(frozen=True)
class InboxPaths:
    schedule: Path
    media_dir: Path
    posted: Path
    offset: Path


def _parse_day(token: str, today: date) -> date | None:
    if token == "hoje":
        return today
    if token in ("amanha", "amanhã"):
        return today + timedelta(days=1)
    try:
        return date.fromisoformat(token)
    except ValueError:
        pass
    match = _DAY_MONTH.fullmatch(token)
    if match:
        day, month, year = match.groups()
        try:
            return date(int(year or today.year), int(month), int(day))
        except ValueError:
            return None
    return None


def _parse_time(token: str) -> time | None:
    match = _TIME.fullmatch(token)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or match.group(3) or 0)
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def parse_when(caption: str | None, now: datetime) -> tuple[date, time] | None:
    """Read "hoje 18:30", "amanhã 12h", "15/11 10:00", "2026-11-15 10:00" or just "18:30".

    An empty caption means "as soon as possible". Returns None when it cannot be understood.
    """
    text = (caption or "").strip().lower()
    if not text:
        return now.date(), time(now.hour, now.minute)
    parts = text.split()
    if len(parts) == 1:
        day_token, time_token = "hoje", parts[0]
    elif len(parts) == 2:
        day_token, time_token = parts
    else:
        return None
    day = _parse_day(day_token, now.date())
    at = _parse_time(time_token)
    if day is None or at is None:
        return None
    return day, at


def extract_attachment(message: dict[str, Any]) -> Attachment | None:
    """The art in a message, None if it carries no media, UnsupportedMedia if it is not usable."""
    if message.get("photo"):
        largest = max(message["photo"], key=lambda p: p.get("width", 0) * p.get("height", 0))
        return Attachment(largest["file_id"], "foto", ".jpg", compressed_photo=True)

    media = message.get("document") or message.get("video")
    if media is None:
        return None
    name = media.get("file_name") or ""
    suffix = Path(name).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
        suffix = MIME_EXTENSIONS.get(media.get("mime_type", ""), "")
    if not suffix:
        raise UnsupportedMedia(name or "unknown")
    return Attachment(media["file_id"], Path(name).stem or "arte", suffix)


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:40] or "arte"


class Inbox:
    def __init__(self, api: TelegramApi, chat_id: str, paths: InboxPaths, now: datetime) -> None:
        self._api = api
        self._chat_id = chat_id
        self._paths = paths
        self._now = now

    def run(self) -> tuple[int, bool]:
        """Handle pending messages. Returns (messages handled, whether it stopped on a failure).

        The offset is saved after every message, so a failure part-way leaves the rest
        waiting for the next run (Telegram keeps them for 24 hours).
        """
        params: dict[str, Any] = {"timeout": 0, "limit": 100, "allowed_updates": ["message"]}
        offset = load_offset(self._paths.offset)
        if offset is not None:
            params["offset"] = offset

        handled = 0
        for update in self._api.call("getUpdates", params):
            try:
                if update.get("message"):
                    self._handle(update["message"])
            except TelegramError as exc:
                log.error("Stopped at update %s: %s", update["update_id"], exc)
                return handled, True
            save_offset(self._paths.offset, update["update_id"] + 1)
            handled += 1
        return handled, False

    # -- message handling ---------------------------------------------------------------

    def _handle(self, message: dict[str, Any]) -> None:
        chat = message["chat"]
        if chat.get("type") != "private" or str(chat["id"]) != self._chat_id:
            log.warning("Ignoring a message from an unauthorized chat")
            return
        try:
            attachment = extract_attachment(message)
        except UnsupportedMedia:
            self._reply("Formato não suportado. Envie JPG, PNG, MP4 ou MOV.")
            return
        if attachment is None:
            self._handle_text(message.get("text") or "")
        else:
            self._handle_art(message["message_id"], attachment, message.get("caption"))

    def _handle_text(self, text: str) -> None:
        parts = text.split()
        command = parts[0].split("@")[0].lower() if parts and text.startswith("/") else ""
        if command == "/start":
            self._reply("Olá! Eu publico Stories no Instagram do restaurante.\n\n" + HELP)
        elif command == "/fila":
            self._reply(self._queue_text())
        elif command == "/cancelar":
            self._reply(self._cancel(parts[1] if len(parts) > 1 else ""))
        else:
            self._reply(HELP)

    def _handle_art(self, message_id: int, art: Attachment, caption: str | None) -> None:
        when = parse_when(caption, self._now)
        if when is None:
            self._reply(BAD_CAPTION)
            return
        day, at = when
        schedule = load_schedule(self._paths.schedule)
        start = datetime.combine(day, at, tzinfo=schedule.timezone)
        if start + schedule.window <= self._now:
            self._reply(
                f"Esse horário ({day:%d/%m/%Y} {at:%H:%M}) já passou. Escolha um horário futuro."
            )
            return

        try:
            file_info = self._api.call("getFile", {"file_id": art.file_id})
            data = self._api.download(file_info["file_path"])
        except TelegramError as exc:
            if "too big" in str(exc).lower():
                self._reply("Arquivo grande demais: o Telegram só entrega arquivos de até 20 MB.")
                return
            raise

        name = f"{day:%Y%m%d}-{_slug(art.stem)}-{message_id}{art.suffix}"
        self._paths.media_dir.mkdir(parents=True, exist_ok=True)
        (self._paths.media_dir / name).write_bytes(data)
        add_one_off(self._paths.schedule, day, at, name)

        when_text = (
            "Sai na próxima rodada, em poucos minutos."
            if start <= self._now
            else f"Agendado para {day:%d/%m/%Y} às {at:%H:%M}."
        )
        lines = [f"✅ Recebi {name}. {when_text}"]
        if art.compressed_photo:
            lines.append(
                "⚠️ Foi enviada como foto e o Telegram comprime. Prefira enviar como arquivo."
            )
        size = image_size(data) if art.suffix in IMAGE_EXTENSIONS else None
        if size and not is_story_ratio(*size):
            lines.append(
                f"⚠️ A imagem tem {size[0]}×{size[1]}, fora de 9:16 (1080×1920). "
                "O Instagram pode cortar ou recusar."
            )
        self._reply("\n".join(lines))

    def _pending(self) -> list[tuple[int, Slot]]:
        """Stories still to go out, as (position in schedule.json, slot).

        The position is the number shown by /fila. It does not change when other Stories are
        posted or expire, so /cancelar N never hits a different Story than the one listed.
        """
        schedule = load_schedule(self._paths.schedule)
        posted = load_posted(self._paths.posted)
        pending: list[tuple[int, Slot]] = []
        for number, slot in enumerate(schedule.slots, start=1):
            if slot.on is not None:
                start = datetime.combine(slot.on, slot.at, tzinfo=schedule.timezone)
                if slot.key(slot.on) in posted or start + schedule.window <= self._now:
                    continue
            pending.append((number, slot))
        return pending

    @staticmethod
    def _describe(slot: Slot) -> str:
        if slot.on is not None:
            return f"{slot.on:%d/%m} {slot.at:%H:%M}"
        days = ", ".join(sorted(slot.days, key=WEEKDAYS.index))
        return f"toda semana ({days}) {slot.at:%H:%M}"

    def _queue_text(self) -> str:
        pending = self._pending()
        if not pending:
            return "Nada agendado."
        one_offs = sorted(
            (p for p in pending if p[1].on), key=lambda p: (p[1].on or date.min, p[1].at)
        )
        recurring = [p for p in pending if not p[1].on]
        lines = [f"{n}. {self._describe(slot)} — {slot.file}" for n, slot in one_offs + recurring]
        return "Agendados:\n" + "\n".join(lines)

    def _cancel(self, argument: str) -> str:
        usage = "Use /cancelar N, com N sendo o número que aparece em /fila."
        if not argument.isdigit():
            return usage
        number = int(argument)
        slot = next((s for n, s in self._pending() if n == number), None)
        if slot is None:
            return f"O número {number} não está na fila. {usage}"

        remove_story(self._paths.schedule, number - 1)
        still_used = any(s.file == slot.file for s in load_schedule(self._paths.schedule).slots)
        art = self._paths.media_dir / slot.file
        if not still_used and art.is_file():
            try:
                art.unlink()
            except OSError as exc:
                log.warning("Could not delete %s: %s", art, exc)
        return f"🗑️ Cancelei {self._describe(slot)} — {slot.file}."

    def _reply(self, text: str) -> None:
        try:
            self._api.call("sendMessage", {"chat_id": self._chat_id, "text": text})
        except TelegramError as exc:
            log.warning("Could not reply on Telegram: %s", exc)
