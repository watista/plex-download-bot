#!/usr/bin/python3

""" Fouten: a Fault is an exception with its kind, and the meldfunctie that writes its line and tells the Beheerder """

import asyncio
import html
import json
import logging
import os
import sys
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from telegram.constants import MessageLimit
from telegram.error import TelegramError

from src.interaction import Interaction, current_interaction, new_code
from src.log import get_logger, is_own_file, source_path

if TYPE_CHECKING:
    # Only for the type: src.telegram_out imports this module
    from src.telegram_out import Delivery


log = get_logger(__name__)


class FaultKind(StrEnum):
    """ The kinds of Fout, written as in the field fault: Bug, Storing and Inrichtingsfout """
    BUG = "bug"
    DISRUPTION = "disruption"
    SETUP = "setup"


class Fault(Exception):
    """ A Fout. Made with Fault.bug, Fault.disruption or Fault.setup, each with only the fields of its kind,
    and raised with `from e` so the original exception and its traceback go along.

    - service: radarr, sonarr, plex, transmission, tmdb, telegram or fallback
    - what: what went wrong, for the head of the admin message ("Radarr refused the movie request")
    - reason: the reason of the service, or the exception
    - http_status: with an HTTP answer
    - check and item, only of an Inrichtingsfout: the check that failed (series_path, tmdb_lookup, setting,
      disk_space) and the tmdb/tvdb ID or the name of the setting. With service they are its key.
    - details: the fields the decision was made on
    - media: the media item, a Radarr or Sonarr item with title, year and tmdbId
    - user_text: a Dutch sentence for the Foutmelding
    """

    def __init__(self, kind: FaultKind, *, what: str, service: str | None = None, reason: str | None = None,
                 http_status: int | None = None, check: str | None = None, item: int | str | None = None,
                 details: dict | None = None, media: dict | None = None, user_text: str | None = None):
        if (kind == FaultKind.SETUP) != (check is not None) or (item is not None and kind != FaultKind.SETUP):
            raise TypeError("only an Inrichtingsfout has a check and an item, and it always has a check")
        if service is None and kind != FaultKind.BUG:
            raise TypeError(f"a Fault of kind {kind} is always of a service")
        super().__init__(what)
        self.kind = kind
        self.service = service
        self.what = what
        self.reason = reason
        self.http_status = http_status
        self.check = check
        self.item = item
        self.details = details
        self.media = media
        self.user_text = user_text

    def __str__(self) -> str:
        return f"{self.what}: {self.reason}" if self.reason else self.what

    @classmethod
    def bug(cls, *, what: str, service: str | None = None, reason: str | None = None, http_status: int | None = None,
            details: dict | None = None, media: dict | None = None, user_text: str | None = None) -> "Fault":
        """ The bot itself does something that is not right; a Bug in the bot's own code has no service """
        return cls(FaultKind.BUG, what=what, service=service, reason=reason, http_status=http_status,
                   details=details, media=media, user_text=user_text)

    @classmethod
    def disruption(cls, *, service: str, what: str, reason: str | None = None, http_status: int | None = None,
                   details: dict | None = None, media: dict | None = None, user_text: str | None = None) -> "Fault":
        """ A service the bot depends on does not respond, or answers with a server error """
        return cls(FaultKind.DISRUPTION, what=what, service=service, reason=reason, http_status=http_status,
                   details=details, media=media, user_text=user_text)

    @classmethod
    def setup(cls, *, service: str, what: str, check: str, item: int | str | None = None, reason: str | None = None,
              http_status: int | None = None, details: dict | None = None, media: dict | None = None,
              user_text: str | None = None) -> "Fault":
        """ Something in the setup of the server is not right, and only the Beheerder can set it right """
        return cls(FaultKind.SETUP, what=what, service=service, reason=reason, http_status=http_status,
                   check=check, item=item, details=details, media=media, user_text=user_text)


# The level of the line of a Fout: ERROR when the Beheerder has to set something right, WARNING for a Storing
LEVELS = {FaultKind.BUG: logging.ERROR, FaultKind.DISRUPTION: logging.WARNING, FaultKind.SETUP: logging.ERROR}

# A Bug with the same signature gets at most one admin message in this time
BUG_THROTTLE = timedelta(hours=24)

# How a month is written in the line Repeat:, in English whatever the locale
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def local_now() -> datetime:
    """ The local time with its offset """
    return datetime.now().astimezone()


class FaultReporter:
    """ The meldfunctie: writes the line of every Fout, and sends the Beheerder an admin message when one is due.

    For now only a Bug gets an admin message; a Storing and an Inrichtingsfout get only their line. send is the
    verzendfunctie, admin_chat_id the chat of the Beheerder, and now the clock. The state lives in state_file
    (faults.json, on dev faults.dev.json), so it survives a restart. It is updated under one lock, because jobs
    and updates run interleaved on the same event loop.
    """

    def __init__(self, send: Callable[..., Awaitable["Delivery"]], admin_chat_id: int | str,
                 state_file: str | os.PathLike, now: Callable[[], datetime] = local_now):
        self._send = send
        self._admin_chat_id = admin_chat_id
        self._state_file = Path(state_file)
        self._now = now
        self._lock = asyncio.Lock()
        self._state = self._load()

    async def report(self, fault: Fault, user_told: bool = False, continued: str | None = None, *,
                     outside_wrapper: bool = False) -> bool:
        """ Writes the line of the Fout, and sends an admin message if one is due.

        Gives back True when the Beheerder knows about this Fout: an admin message went out now, or did earlier
        within the throttle. user_told says the wrapper is going to tell the user; continued how the code went on
        after reporting the Fout, and outside_wrapper that error_handler caught it.
        """

        # Taken first: the caller is src of a Fault that was never raised
        caller = _place(sys._getframe(1))
        interaction = current_interaction()

        # Only a Bug outside an Interaction gets a Code of its own
        code = interaction.code if interaction else new_code() if fault.kind == FaultKind.BUG else None
        stack = _stack(fault)
        own = [frame for frame in stack if is_own_file(frame.filename)]
        innermost = own[-1] if own else caller
        media = _media(fault, interaction)

        if fault.kind != FaultKind.BUG:
            # The admin messages about a Storing and an Inrichtingsfout follow in issue 08
            self._write(fault, innermost, code, media, full=True)
            return False

        # Decided and written down before sending, so a Bug that comes again meanwhile gets no second message
        signature = _signature(fault, innermost)
        now = self._now()
        async with self._lock:
            last = self._bugs.get(signature)
            times = last["repeat"] + 1 if last else 0
            due = last is None or now - datetime.fromisoformat(last["last_admin_message"]) >= BUG_THROTTLE
            if due:
                self._bugs[signature] = {"last_admin_message": now.isoformat(), "repeat": 0}
            else:
                self._bugs[signature] = {**last, "repeat": times}
            self._save()

        self._write(fault, innermost, code, media, full=due, repeat=None if due else times)
        if not due:
            return True

        frames = [_src(frame) for frame in reversed(own or stack[-3:] or [caller])]
        repeat = f"{times}× since the last alert ({_moment(last['last_admin_message'], now)})" if last else None
        text = admin_message_html(fault, interaction or Interaction(code), frames, user_told, continued,
                                  outside_wrapper, repeat)
        if await self._send_admin_message(text, fault, code):
            return True

        # The Beheerder does not know yet, so the next time sends the message again. A Bug that came again
        # meanwhile still counts; only before a first message there is nothing to count from.
        async with self._lock:
            current = self._bugs.get(signature)
            if current is not None and current["last_admin_message"] == now.isoformat():
                if last is None:
                    del self._bugs[signature]
                else:
                    self._bugs[signature] = {**last, "repeat": times + current["repeat"]}
                self._save()
        return False

    def _write(self, fault: Fault, innermost: traceback.FrameSummary, code: str | None, media: dict | None,
               full: bool, repeat: int | None = None) -> None:
        """ The line of a Fout: full, or short with repeat, without the traceback and the decision fields.

        msg holds the reason of the service, or else the exception the Fault came from. Only a Bug gets the
        traceback, in exc.
        """
        original = _original_exception(fault)
        if fault.reason:
            msg = f"{fault.what}: {fault.reason}"
        elif original is not None:
            msg = f"{fault.what}: {_exception_text(original)}"
        else:
            msg = fault.what
        exc = None
        if full and fault.kind == FaultKind.BUG and (original is not None or fault.__traceback__ is not None):
            exc = "".join(traceback.format_exception(fault)).rstrip("\n")

        log.log(LEVELS[fault.kind], msg, at=innermost, media=media, reason=fault.reason,
                http_status=fault.http_status, repeat=repeat, details=fault.details if full else None,
                fault=fault.kind, service=fault.service, interaction_id=code,
                exc_type=type(original).__name__ if original is not None else None, exc=exc)

    async def _send_admin_message(self, text: str, fault: Fault, code: str | None) -> bool:
        """ Sends the admin message about a Fout through the verzendfunctie; True when it arrived """
        about = f"{fault.kind.title()} · {fault.what}"
        try:
            reason = (await self._send(self._admin_chat_id, text, "HTML")).reason
        except Fault as unsent:
            # Telegram is not responding: a Storing of its own. Not sent meanwhile follows in issue 11.
            await self.report(unsent)
            return False
        except TelegramError as e:
            # Telegram did answer, but not with the message, like a chat that does not exist
            reason = e.message
        if reason is not None:
            log.warning(f"admin message not delivered: {about}: {reason}", reason=reason, interaction_id=code)
            return False
        log.info(f"admin message sent: {about}", event="admin_message_sent", fault=fault.kind, service=fault.service,
                 interaction_id=code)
        return True

    @property
    def _bugs(self) -> dict:
        """ Per signature of a Bug: the last admin message, and how often it came since """
        return self._state["bugs"]

    def _load(self) -> dict:
        """ The state from the state file: empty without one, or when it cannot be read """
        try:
            state = json.loads(self._state_file.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("not a JSON object")
        except FileNotFoundError:
            state = {}
        except (OSError, ValueError) as e:
            # Better an admin message about a Bug once more, than a bot that does not start
            log.warning(f"could not read {self._state_file.name}, starting without the state of earlier Fouten: {e}")
            state = {}
        state.setdefault("bugs", {})
        return state

    def _save(self) -> None:
        """ Writes the state through a temporary file, so a crash never leaves half a state behind """
        temporary = self._state_file.with_name(f"{self._state_file.name}.tmp")
        try:
            temporary.write_text(json.dumps(self._state, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(temporary, self._state_file)
        except OSError as e:
            # The state stays in memory; reporting the Fout goes on
            log.error(f"could not write {self._state_file.name}: {e}")


def _place(frame) -> traceback.FrameSummary:
    """ The place in the code that a running frame is at """
    return traceback.FrameSummary(frame.f_code.co_filename, frame.f_lineno, frame.f_code.co_name, lookup_line=False)


def _original_exception(exception: BaseException) -> BaseException | None:
    """ The exception this one was raised from (raise Fault(...) from e), None if the bot raised it of its own.

    Only from: an exception that was being handled while the Fault was raised is not where it came from.
    """
    return exception.__cause__


def _chain(exception: BaseException) -> list[BaseException]:
    """ The exception and those it was raised from, the outermost first """
    chain = []
    while exception is not None and not any(exception is seen for seen in chain):
        chain.append(exception)
        exception = _original_exception(exception)
    return chain


def _stack(fault: Fault) -> list[traceback.FrameSummary]:
    """ The frames of the Fault and the exceptions it came from, the outermost first, down to where it started.

    An exception that was caught and raised again as a Fault (raise Fault(...) from e) goes on from the frame that
    caught it, at the line where e happened there.
    """
    stack = []
    for exception in _chain(fault):
        frames = list(traceback.walk_tb(exception.__traceback__))
        if frames:
            caught = next((i for i, (frame, _) in enumerate(stack) if frame is frames[0][0]), len(stack))
            stack = stack[:caught] + frames
    return [traceback.FrameSummary(frame.f_code.co_filename, line, frame.f_code.co_name, lookup_line=False)
            for frame, line in stack]


def _src(frame: traceback.FrameSummary) -> str:
    """ A frame the way the field src writes it: path:line in function """
    return f"{source_path(frame.filename)}:{frame.lineno} in {frame.name}"


def _signature(fault: Fault, innermost: traceback.FrameSummary) -> str:
    """ What makes two Bugs the same Bug.

    The service, the type of the exception (Fault when the bot raised it of its own), the innermost own frame, and
    the status of a 4xx. Not the reason, which holds titles.
    """
    original = _original_exception(fault)
    status = fault.http_status if fault.http_status and 400 <= fault.http_status < 500 else None
    parts = (fault.service or "-", type(original if original is not None else fault).__name__,
             f"{source_path(innermost.filename)}:{innermost.lineno}", status)
    return " ".join(str(part) for part in parts if part is not None)


def _media(fault: Fault, interaction: Interaction | None) -> dict | None:
    """ The media item of a Fout: that of the Fault, or else the one the Interaction was working on """
    return fault.media or (interaction.media if interaction else None)


def _moment(moment: str, now: datetime) -> str:
    """ A moment in local time for the line Repeat:, like 12 Oct 14:02, with the year when it is not this year """
    local = datetime.fromisoformat(moment).astimezone()
    year = f" {local.year}" if local.year != now.astimezone().year else ""
    return f"{local.day} {MONTHS[local.month - 1]}{year} {local:%H:%M}"


def _exception_text(exception: BaseException) -> str:
    """ The type of an exception with its text, like JSONDecodeError: Expecting value """
    return f"{type(exception).__name__}: {exception}" if str(exception) else type(exception).__name__


# The head of an admin message per kind of Fout: the kind as in the field fault, with a capital
HEADS = {FaultKind.BUG: "🐞 <b>Bug</b>", FaultKind.DISRUPTION: "🌩 <b>Disruption</b>", FaultKind.SETUP: "🔧 <b>Setup</b>"}

# The most characters of the reason or the exception in an admin message
MAX_REASON = 300

# The end of an expandable block that was cut to fit in one message
TRUNCATED = "… truncated, see log"


def admin_message_html(fault: Fault, interaction: Interaction, frames: list[str], user_told: bool,
                       continued: str | None = None, outside_wrapper: bool = False, repeat: str | None = None) -> str:
    """ The admin message about a Fout, in HTML.

    interaction is the Interaction the Fout happened in: its Code, who, and the media item it was working on, which
    the Fault's own media overrules. frames are the own frames, the innermost first. user told is only there with a
    person: a job never tells anyone. continued says how the code went on after reporting the Fout, outside_wrapper
    that error_handler caught it, and repeat is the text of the line Repeat: of a message that is a repetition.
    """
    media = _media(fault, interaction)

    # In view: the reason of the service, and the exception the Fault was raised from
    lines = [f"{HEADS[fault.kind]} · {_escape(fault.what)}"]
    if fault.reason:
        status = f" (HTTP {fault.http_status})" if fault.http_status else ""
        lines.append(f"Reason: <i>{_escape(_cut(fault.reason))}</i>{status}")
    if (original := _original_exception(fault)) is not None:
        text = f": {_escape(_cut(str(original)))}" if str(original) else ""
        lines.append(f"Exception: <code>{type(original).__name__}</code>{text}")
    if interaction.account:
        lines.append(f"User: {_escape(interaction.account)}")
    elif interaction.tg_name:
        lines.append(f"Visitor: {_escape(interaction.tg_name)}")
    elif interaction.job:
        lines.append(f"Job: <code>{_escape(interaction.job)}</code>")
    if media:
        lines.append(f"Media: {_escape(_title(media))}")
    if outside_wrapper:
        lines.append("Caught by error_handler, outside the wrapper")
    if continued:
        lines.append(f"Continued: {_escape(continued)}")
    if repeat:
        lines.append(f"Repeat: {_escape(repeat)}")

    # In the expandable block: the decision fields, the own code, the ID of the media, and the person
    block = [_Piece(f"{key}: {value}") for key, value in (fault.details or {}).items()]
    if frames:
        block.append(_Piece("\n".join(frames), code=True))
    if media and (media.get("tmdbId") or media.get("tvdbId")):
        block.append(_Piece(f"tmdb {media['tmdbId']}" if media.get("tmdbId") else f"tvdb {media['tvdbId']}"))
    if interaction.user_id:
        block.append(_Piece(f"user_id: {interaction.user_id}"))
        block.append(_Piece(f"user told: {'yes' if user_told else 'no'}"))

    return _fit(lines, block, f"Code: <code>{_escape(interaction.code)}</code>")


@dataclass(frozen=True)
class _Piece:
    """ A piece of the expandable block, unescaped, and whether it is code """
    text: str
    code: bool = False

    def html(self) -> str:
        return f"<code>{_escape(self.text)}</code>" if self.code else _escape(self.text)


def _fit(head: list[str], block: list[_Piece], tail: str) -> str:
    """ The message, with as much of the block as fits in one message of Telegram.

    A block that does not fit is cut from the back and ends with TRUNCATED. The cut falls between two characters
    of a piece, so never in a tag or an entity.
    """

    def message(pieces: list[_Piece], cut: bool = False) -> str:
        inner = [piece.html() for piece in pieces] + ([TRUNCATED] if cut else [])
        quote = ["<blockquote expandable>" + "\n".join(inner) + "</blockquote>"] if inner else []
        return "\n".join([*head, *quote, tail])

    def fits(pieces: list[_Piece]) -> bool:
        return len(message(pieces, cut=True)) <= MessageLimit.MAX_TEXT_LENGTH

    whole = message(block)
    if len(whole) <= MessageLimit.MAX_TEXT_LENGTH or not block:
        # Without a block there is nothing to cut here; the verzendfunctie cuts at the limit
        return whole

    # As many whole pieces as fit, then the longest start of the next piece that fits
    kept = len(block) - 1
    while kept > 0 and not fits(block[:kept]):
        kept -= 1
    piece = block[kept]
    shortest, longest = 0, len(piece.text) - 1
    while shortest < longest:
        middle = (shortest + longest + 1) // 2
        if fits([*block[:kept], replace(piece, text=piece.text[:middle])]):
            shortest = middle
        else:
            longest = middle - 1
    start = [replace(piece, text=piece.text[:shortest])] if shortest else []
    return message([*block[:kept], *start], cut=True)


def _escape(text: str) -> str:
    """ The text with only < > & escaped, as the HTML of Telegram needs """
    return html.escape(text, quote=False)


def _cut(text: str) -> str:
    """ The text cut at MAX_REASON characters """
    return text if len(text) <= MAX_REASON else f"{text[:MAX_REASON - 1]}…"


def _title(media: dict) -> str:
    """ Title and year of a media item, like Dune: Part Two (2024) """
    return f"{media.get('title')} ({media['year']})" if media.get("year") else f"{media.get('title')}"
