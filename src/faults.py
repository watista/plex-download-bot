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

from src.interaction import Interaction, current_code, current_interaction, new_code
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

# A Storing persists from 2 failed attempts, the last at least this long after the first
PERSISTS_AFTER = timedelta(minutes=15)

# The wait after an admin message about a Storing or an Inrichtingsfout, before a Herinnering: after the 1st
# admin message 1 day, after the 2nd 3 days, and from then on 7 days
REMINDER_WAITS = (timedelta(days=1), timedelta(days=3), timedelta(days=7))

# An Inrichtingsfout that did not come for this long is forgotten without a Herstelmelding: the bot does not know
# whether it was set right, or is no longer checked
FORGET_SETUP_AFTER = timedelta(days=30)

# How a month is written in the line Repeat:, in English whatever the locale
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def local_now() -> datetime:
    """ The local time with its offset """
    return datetime.now().astimezone()


@dataclass(frozen=True)
class _Occurrence:
    """ One time a Fout comes: the Fault, the Interaction it came in and its Code, where in the code, and what the
    caller of report() said about it. frames are the own frames for the admin message, the innermost first.
    """
    fault: Fault
    interaction: Interaction | None
    code: str | None
    innermost: traceback.FrameSummary
    frames: list[str]
    user_told: bool
    continued: str | None
    outside_wrapper: bool


class FaultReporter:
    """ The meldfunctie: writes the line of every Fout, and sends the Beheerder an admin message when one is due.

    send is the verzendfunctie, admin_chat_id the chat of the Beheerder, and now the clock. The state lives in
    state_file (faults.json, on dev faults.dev.json), so it survives a restart. It is updated under one lock,
    because jobs and updates run interleaved on the same event loop.
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

        Gives back True when the Beheerder knows about this Fout: an admin message went out now, or did earlier,
        within the throttle of a Bug or while the Storing or Inrichtingsfout is open. user_told says the wrapper is
        going to tell the user; continued how the code went on after reporting the Fout, and outside_wrapper that
        error_handler caught it.
        """

        # Taken first: the caller is src of a Fault that was never raised
        caller = _place(sys._getframe(1))
        interaction = current_interaction()

        # Only a Bug outside an Interaction gets a Code of its own
        code = interaction.code if interaction else new_code() if fault.kind == FaultKind.BUG else None
        stack = _stack(fault)
        own = [frame for frame in stack if is_own_file(frame.filename)]
        occurrence = _Occurrence(fault, interaction, code, innermost=own[-1] if own else caller,
                                 frames=[_src(frame) for frame in reversed(own or stack[-3:] or [caller])],
                                 user_told=user_told, continued=continued, outside_wrapper=outside_wrapper)

        if fault.kind == FaultKind.BUG:
            return await self._report_bug(occurrence)
        if fault.kind == FaultKind.SETUP:
            return await self._report_setup(occurrence)
        return await self._report_disruption(occurrence)

    async def ok(self, service: str) -> None:
        """ A successful answer of service, to any request: it ends the Storing of that service.

        Without an open Storing this costs next to nothing, so it can follow every successful answer.
        """
        if service not in self._disruptions:
            return
        now = self._now()
        async with self._lock:
            ended = self._disruptions.pop(service, None)
            if ended is None:
                return
            self._save()
        since = datetime.fromisoformat(ended["since"])
        if service == "telegram":
            await self._telegram_restored(ended, since, now)
            return
        if not ended["admin_messages"]:
            # Over before it persisted: it leaves only its lines
            return

        code = current_code()
        text = restored_html(service, since, now, ended["attempts"], ended["first_code"], code)
        await self._send_admin_message(text, f"Restored · {_service_name(service)} is responding again",
                                       FaultKind.DISRUPTION, service, code, restored=True)

    async def _telegram_restored(self, ended: dict, since: datetime, now: datetime) -> None:
        """ The Herstelmelding after the Storing of Telegram that ended, when it persisted or an admin message about
        a Fout did not go out meanwhile.

        It has no Code: polling is outside an Interaction. It comes with sound when it lists admin messages that
        did not go out.
        """
        not_sent = ended.get("not_sent", [])
        if not ended.get("persisted") and not not_sent:
            return
        text = restored_html("telegram", since, now, ended["attempts"], None, None, not_sent)
        if await self._send_admin_message(text, "Restored · Telegram is responding again", FaultKind.DISRUPTION,
                                          "telegram", None, restored=True, silent=not not_sent):
            return

        # When Telegram stopped responding again, this Storing goes on in the new one: its Herstelmelding then
        # covers both, from the begin of this one, with its attempts and its list
        async with self._lock:
            if (current := self._disruptions.get("telegram")) is not None:
                current["since"] = ended["since"]
                current["first_code"] = ended["first_code"]
                current["attempts"] += ended["attempts"]
                current["persisted"] = bool(ended.get("persisted") or current.get("persisted"))
                current["not_sent"] = _with_not_sent(not_sent, current.get("not_sent", []))
                self._save()

    async def fixed(self, service: str, check: str, item: int | str | None, msg: str) -> None:
        """ The check of an Inrichtingsfout succeeded; msg says what is right now, like "Carrie now has a path in
        Sonarr". service, check and item are those of the Fault, without an item when it has none (disk_space).

        After an admin message about the Fout a silent Herstelmelding follows; otherwise this only clears its state.
        Without that Fout open this costs next to nothing, so it can follow every check that succeeds.
        """
        key = _setup_key(service, check, item)
        if key not in self._setup:
            return
        now = self._now()
        async with self._lock:
            _forget_old_setup_faults(self._setup, now)
            ended = self._setup.pop(key, None)
            self._save()
        if ended is None or not ended["admin_messages"]:
            return

        code = current_code()
        text = fixed_html(msg, datetime.fromisoformat(ended["since"]), now, ended["times"], ended["first_code"], code)
        await self._send_admin_message(text, f"Fixed · {msg}", FaultKind.SETUP, service, code, restored=True)

    async def _report_setup(self, occurrence: _Occurrence) -> bool:
        """ An Inrichtingsfout: an admin message at once, and a Herinnering when it comes again after each wait """
        fault, code, now = occurrence.fault, occurrence.code, self._now()
        key = _setup_key(fault.service, fault.check, fault.item)
        async with self._lock:
            _forget_old_setup_faults(self._setup, now)
            before = self._setup.get(key)
            current = dict(before) if before else {"since": now.isoformat(), "times": 0, "last_code": None,
                                                   "first_code": None, "admin_messages": 0,
                                                   "last_admin_message": None, "repeat": 0}
            # It counts per run, not per call: a job may run into the same Fout twice
            if before is None or code is None or code != before["last_code"]:
                current["times"] += 1
            current["last_code"] = code
            current["last_seen"] = now.isoformat()
            due = _admin_message_due(current, now)
            held = due and self._telegram_is_down()
            due = due and not held
            full = before is None or due
            current["repeat"] = 0 if full else current["repeat"] + 1
            if due:
                current["admin_messages"] += 1
                current["last_admin_message"] = now.isoformat()
                if current["admin_messages"] == 1:
                    # The Code that the Herstelmelding starts from
                    current["first_code"] = code
            self._setup[key] = current
            self._save()

        self._write(occurrence, full=full, repeat=None if full else current["repeat"])
        known = before is not None and before["admin_messages"] > 0
        if held:
            await self._hold_back(_about(fault), fault.kind, fault.service, code, key)
        if not due:
            return known

        since = _day_and_time(datetime.fromisoformat(current["since"]), now)
        failing = f"failing since {since} ({current['times']:,}×)"
        text = admin_message_html(fault, occurrence.interaction, occurrence.frames, occurrence.user_told,
                                  occurrence.continued, occurrence.outside_wrapper, _repeat(current, now, failing))
        return await self._send_or_take_back(text, occurrence, self._setup, key, before, now) or known

    async def _report_disruption(self, occurrence: _Occurrence) -> bool:
        """ A failed attempt of a Storing: an admin message once the Storing persists, and then a Herinnering at
        the first failed attempt after each wait.

        No admin message about Telegram can arrive: its Storing only counts, for the Herstelmelding when it is over.
        """
        fault, now = occurrence.fault, self._now()
        async with self._lock:
            before = self._disruptions.get(fault.service)
            current = dict(before) if before else {"since": now.isoformat(), "first_code": occurrence.code,
                                                   "attempts": 0, "admin_messages": 0,
                                                   "last_admin_message": None, "repeat": 0}
            current["attempts"] += 1
            current["last_reason"] = _cause(fault)
            since = datetime.fromisoformat(current["since"])
            persists = current["attempts"] >= 2 and now - since >= PERSISTS_AFTER
            if fault.service == "telegram":
                current["persisted"] = persists
                due = held = False
            else:
                due = persists and _admin_message_due(current, now)
                held = due and self._telegram_is_down()
                due = due and not held
            full = before is None or due
            current["repeat"] = 0 if full else current["repeat"] + 1
            if due:
                current["admin_messages"] += 1
                current["last_admin_message"] = now.isoformat()
            self._disruptions[fault.service] = current
            self._save()

        self._write(occurrence, full, repeat=None if full else current["repeat"])
        known = before is not None and before["admin_messages"] > 0
        if held:
            await self._hold_back(_about(fault), fault.kind, fault.service, occurrence.code, fault.service)
        if not due:
            return known

        # About the service, not about whom it affected: the Code is that of the first failed attempt
        first = Interaction(current["first_code"]) if current["first_code"] else None
        text = admin_message_html(fault, first, occurrence.frames, occurrence.user_told, occurrence.continued,
                                  occurrence.outside_wrapper, _repeat(current, now),
                                  since=f"{_time_or_day_and_time(since, now)}, {current['attempts']:,} failed attempts")
        return await self._send_or_take_back(text, occurrence, self._disruptions, fault.service, before, now) or known

    async def _send_or_take_back(self, text: str, occurrence: _Occurrence, entries: dict, key: str,
                                 before: dict | None, now: datetime) -> bool:
        """ Sends the admin message about entries[key] that was decided at now; True when it arrived.

        One that did not arrive is taken back, so the next time the Fout comes sends it again.
        """
        fault = occurrence.fault
        if await self._send_admin_message(text, _about(fault), fault.kind, fault.service, occurrence.code, key):
            return True
        async with self._lock:
            if _take_back_admin_message(entries, key, before, now):
                self._save()
        return False

    async def _report_bug(self, occurrence: _Occurrence) -> bool:
        """ A Bug: an admin message at most once per 24 hours per signature """
        fault, code = occurrence.fault, occurrence.code

        # Decided and written down before sending, so a Bug that comes again meanwhile gets no second message
        signature = _signature(fault, occurrence.innermost)
        now = self._now()
        async with self._lock:
            last = self._bugs.get(signature)
            times = last["repeat"] + 1 if last else 0
            alerted = last["last_admin_message"] if last else None
            due = alerted is None or now - datetime.fromisoformat(alerted) >= BUG_THROTTLE
            held = due and self._telegram_is_down()
            if held:
                # Kept without an admin message, so the next time is not its first
                self._bugs[signature] = {"last_admin_message": alerted, "repeat": times}
            elif due:
                self._bugs[signature] = {"last_admin_message": now.isoformat(), "repeat": 0}
            else:
                self._bugs[signature] = {**last, "repeat": times}
            self._save()

        full = last is None or (due and not held)
        self._write(occurrence, full=full, repeat=None if full else times)
        if held:
            await self._hold_back(_about(fault), fault.kind, fault.service, code, signature)
            return False
        if not due:
            return True

        repeat = None
        if alerted:
            previous = _day_and_time(datetime.fromisoformat(alerted), now)
            repeat = f"{times}× since the last alert ({previous})"
        text = admin_message_html(fault, occurrence.interaction or Interaction(code), occurrence.frames,
                                  occurrence.user_told, occurrence.continued, occurrence.outside_wrapper, repeat)
        if await self._send_admin_message(text, _about(fault), fault.kind, fault.service, code, signature):
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

    def _write(self, occurrence: _Occurrence, full: bool, repeat: int | None = None) -> None:
        """ The line of a Fout: full, or short with repeat, without the traceback and the decision fields.

        msg holds the reason of the service, or else the exception the Fault came from. Only a Bug gets the
        traceback, in exc.
        """
        fault = occurrence.fault
        original = _original_exception(fault)
        cause = _cause(fault)
        exc = None
        if full and fault.kind == FaultKind.BUG and (original is not None or fault.__traceback__ is not None):
            exc = "".join(traceback.format_exception(fault)).rstrip("\n")

        log.log(LEVELS[fault.kind], f"{fault.what}: {cause}" if cause else fault.what, at=occurrence.innermost,
                media=_media(fault, occurrence.interaction), reason=fault.reason, http_status=fault.http_status,
                repeat=repeat, details=fault.details if full else None, fault=fault.kind, service=fault.service,
                interaction_id=occurrence.code, exc_type=type(original).__name__ if original is not None else None,
                exc=exc)

    async def _send_admin_message(self, text: str, about: str, kind: FaultKind, service: str | None,
                                  code: str | None, key: str | None = None, restored: bool = False,
                                  silent: bool | None = None) -> bool:
        """ Sends an admin message about a Fout through the verzendfunctie; True when it arrived.

        about is what the line admin_message_sent says it was about, and key what makes the Fout the same Fout: the
        signature of a Bug, the key of an Inrichtingsfout or the service of a Storing. A Herstelmelding (restored) has
        no key, and comes in silently unless silent says otherwise.

        While Telegram is not responding nothing is tried: an admin message about a Fout goes on the list Not sent
        meanwhile instead.
        """
        if await self._hold_back(about, kind, service, code, key):
            return False
        try:
            reason = (await self._send(self._admin_chat_id, text, "HTML",
                                       silent=restored if silent is None else silent)).reason
        except Fault as unsent:
            # Telegram is not responding: a Storing of its own, which holds back this admin message too
            await self.report(unsent)
            await self._hold_back(about, kind, service, code, key)
            return False
        except TelegramError as e:
            # Telegram did answer, but not with the message, like a chat that does not exist
            reason = e.message
        if reason is not None:
            log.warning(f"admin message not delivered: {about}: {reason}", reason=reason, interaction_id=code)
            return False
        log.info(f"admin message sent: {about}", event="admin_message_sent", fault=kind, service=service,
                 restored=restored or None, interaction_id=code)
        return True

    async def _hold_back(self, about: str, kind: FaultKind, service: str | None, code: str | None,
                         key: str | None) -> bool:
        """ Holds back an admin message while Telegram is not responding: False when there is no Storing of Telegram.

        One about a Fout goes on the list Not sent meanwhile of that Storing: once per Fout, with the Code of the
        first time. A Herstelmelding (no key) does not. Only an admin message that is not on the list yet gets a
        line, so a Fout that comes every few seconds does not add one each time.
        """
        if not self._telegram_is_down():
            return False
        reason = "Telegram is not responding"
        async with self._lock:
            # Looked at again under the lock: a successful answer may have ended the Storing meanwhile
            if (telegram := self._disruptions.get("telegram")) is None:
                return False
            listed = telegram.get("not_sent", [])
            entry = {"key": f"{kind} {key}", "fault": kind, "service": service, "code": code}
            telegram["not_sent"] = _with_not_sent(listed, [entry] if key is not None else [])
            new = len(telegram["not_sent"]) > len(listed)
            if new:
                self._save()
        if new or key is None:
            log.warning(f"admin message not sent: {about}: {reason}", reason=reason, interaction_id=code)
        return True

    def _telegram_is_down(self) -> bool:
        """ Whether a Storing of Telegram is open. Then no admin message is decided or tried: a Fout whose admin
        message is due goes on the list Not sent meanwhile, gets a short line after its first, and its admin message
        goes out the first time it comes after the Storing.
        """
        return "telegram" in self._disruptions

    @property
    def _bugs(self) -> dict:
        """ Per signature of a Bug: the last admin message, None while none went out, and how often it came since """
        return self._state["bugs"]

    @property
    def _disruptions(self) -> dict:
        """ Per service with an open Storing: since when, the Code of the first failed attempt, the attempts, the
        last reason, the admin messages so far with the last, and the short lines since the last full one. That of
        Telegram also has whether it persisted, and the list Not sent meanwhile (not_sent).
        """
        return self._state["disruptions"]

    @property
    def _setup(self) -> dict:
        """ Per key of an Inrichtingsfout: since when, how often, when it came last, the Code of the first admin
        message, the admin messages so far with the last, and the short lines since the last full one
        """
        return self._state["setup"]

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
        state.setdefault("disruptions", {})
        state.setdefault("setup", {})
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


def _about(fault: Fault) -> str:
    """ What the line admin_message_sent says an admin message about this Fout was about, like Bug · what """
    return f"{fault.kind.title()} · {fault.what}"


def _admin_message_due(entry: dict, now: datetime) -> bool:
    """ Whether a Storing or an Inrichtingsfout is due for an admin message: its first, or a Herinnering after the
    wait since the previous one
    """
    if not entry["admin_messages"]:
        return True
    return now - datetime.fromisoformat(entry["last_admin_message"]) >= _wait(entry["admin_messages"])


def _take_back_admin_message(entries: dict, key: str, before: dict | None, now: datetime) -> bool:
    """ Takes back the admin message about entries[key] that was decided at now and did not arrive, so the next
    time sends it again: not when the Fout ended meanwhile, or another admin message was decided since. Gives back
    whether it changed anything.
    """
    current = entries.get(key)
    if current is None or current["last_admin_message"] != now.isoformat():
        return False
    entries[key] = {**current, "admin_messages": before["admin_messages"] if before else 0,
                    "last_admin_message": before["last_admin_message"] if before else None}
    return True


def _with_not_sent(listed: list[dict], more: list[dict]) -> list[dict]:
    """ The list Not sent meanwhile with more added, each Fout once: of a Fout already on it, the entry of the first
    time stays """
    keys = {entry["key"] for entry in listed}
    return [*listed, *(entry for entry in more if entry["key"] not in keys)]


def _forget_old_setup_faults(setup: dict, now: datetime) -> None:
    """ Forgets the Inrichtingsfouten that did not come for FORGET_SETUP_AFTER: coming back, one is a new Fout """
    for key, entry in list(setup.items()):
        if now - datetime.fromisoformat(entry["last_seen"]) >= FORGET_SETUP_AFTER:
            del setup[key]


def _wait(admin_messages: int) -> timedelta:
    """ The wait for a Herinnering after this many admin messages """
    return REMINDER_WAITS[min(admin_messages, len(REMINDER_WAITS)) - 1]


def _repeat(entry: dict, now: datetime, failing: str = "") -> str | None:
    """ The line Repeat: of the admin message that entry is due for now, None for its first.

    failing goes between which alert it is and the next one, like "failing since 1 Oct 06:27 (96×)". The message
    itself says "alert", as the spec writes it.
    """
    if entry["admin_messages"] < 2:
        return None
    return " · ".join(part for part in (f"{_ordinal(entry['admin_messages'])} alert", failing,
                                        f"next alert {_day(now + _wait(entry['admin_messages']), now)}") if part)


def _ordinal(n: int) -> str:
    """ 1st, 2nd, 3rd, 4th, …, 11th, 12th, 13th, …, 21st """
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _day(moment: datetime, now: datetime) -> str:
    """ The day of a moment in local time, like 5 Nov, with the year when it is not this year """
    local = moment.astimezone()
    year = f" {local.year}" if local.year != now.astimezone().year else ""
    return f"{local.day} {MONTHS[local.month - 1]}{year}"


def _day_and_time(moment: datetime, now: datetime) -> str:
    """ A moment in local time, like 12 Oct 14:02, with the year when it is not this year """
    return f"{_day(moment, now)} {moment.astimezone():%H:%M}"


def _time_or_day_and_time(moment: datetime, now: datetime) -> str:
    """ A moment in local time: only the time when it is today, like 05:02, or else like 1 Nov 17:37 """
    if moment.astimezone().date() == now.astimezone().date():
        return f"{moment.astimezone():%H:%M}"
    return _day_and_time(moment, now)


def _exception_text(exception: BaseException) -> str:
    """ The type of an exception with its text, like JSONDecodeError: Expecting value """
    return f"{type(exception).__name__}: {exception}" if str(exception) else type(exception).__name__


def _cause(fault: Fault) -> str | None:
    """ What the Fout came from: the reason of the service, or else the exception the Fault was raised from """
    original = _original_exception(fault)
    return fault.reason or (_exception_text(original) if original is not None else None)


# The head of an admin message per kind of Fout: the kind as in the field fault, with a capital
HEADS = {FaultKind.BUG: "🐞 <b>Bug</b>", FaultKind.DISRUPTION: "🌩 <b>Disruption</b>", FaultKind.SETUP: "🔧 <b>Setup</b>"}

# The most characters of the reason or the exception in an admin message
MAX_REASON = 300

# The end of an expandable block that was cut to fit in one message
TRUNCATED = "… truncated, see log"


def admin_message_html(fault: Fault, interaction: Interaction | None, frames: list[str], user_told: bool,
                       continued: str | None = None, outside_wrapper: bool = False, repeat: str | None = None,
                       since: str | None = None) -> str:
    """ The admin message about a Fout, in HTML.

    interaction is the Interaction the Fout happened in, None outside one: its Code, who, and the media item it was
    working on, which the Fault's own media overrules. A Storing is about its service, not about whom it affected:
    it leaves out who and the media, and its Code is that of the first failed attempt. frames are the own frames,
    the innermost first, which only a Bug shows. user told is only there with a person: a job never tells anyone.
    continued says how the code went on after reporting the Fout, outside_wrapper that error_handler caught it,
    repeat is the text of the line Repeat: of a message that is a repetition, and since that of the line Since: of
    a Storing.
    """
    disruption = fault.kind == FaultKind.DISRUPTION
    person = None if disruption else interaction
    media = None if disruption else _media(fault, interaction)

    # In view: the reason of the service, and the exception the Fault was raised from
    lines = [f"{HEADS[fault.kind]} · {_escape(fault.what)}"]
    if fault.reason:
        status = f" (HTTP {fault.http_status})" if fault.http_status else ""
        lines.append(f"Reason: <i>{_escape(_cut(fault.reason))}</i>{status}")
    if (original := _original_exception(fault)) is not None:
        text = f": {_escape(_cut(str(original)))}" if str(original) else ""
        lines.append(f"Exception: <code>{type(original).__name__}</code>{text}")
    if since:
        lines.append(f"Since: {_escape(since)}")
    if person and person.account:
        lines.append(f"User: {_escape(person.account)}")
    elif person and person.tg_name:
        lines.append(f"Visitor: {_escape(person.tg_name)}")
    elif person and person.job:
        lines.append(f"Job: <code>{_escape(person.job)}</code>")
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
    if frames and fault.kind == FaultKind.BUG:
        block.append(_Piece("\n".join(frames), code=True))
    if media and (media.get("tmdbId") or media.get("tvdbId")):
        block.append(_Piece(f"tmdb {media['tmdbId']}" if media.get("tmdbId") else f"tvdb {media['tvdbId']}"))
    if person and person.user_id:
        block.append(_Piece(f"user_id: {person.user_id}"))
        block.append(_Piece(f"user told: {'yes' if user_told else 'no'}"))

    tail = []
    if interaction is not None:
        first = " (first failed attempt)" if disruption else ""
        tail.append(f"Code: <code>{_escape(interaction.code)}</code>{first}")
    return _fit(lines, block, tail)


# The most Fouten that the Herstelmelding after a Storing of Telegram lists by name; the rest is +N more
MAX_NOT_SENT = 10

# How a service is called in the head of a Herstelmelding
SERVICE_NAMES = {"radarr": "Radarr", "sonarr": "Sonarr", "plex": "Plex", "transmission": "Transmission",
                 "tmdb": "TMDB", "telegram": "Telegram", "fallback": "The fallback host"}


def restored_html(service: str, since: datetime, now: datetime, attempts: int, first_code: str | None,
                  code: str | None, not_sent: list[dict] | None = None) -> str:
    """ The Herstelmelding after a Storing that persisted, in HTML: its begin and end, how long, how many failed
    attempts, and the Code of the first failed attempt → that of the first successful answer.

    After a Storing of Telegram, not_sent are the Fouten whose admin message did not go out meanwhile, each with
    the kind, the service and the Code in faults.json: at most MAX_NOT_SENT of them, and how many more.
    """
    listed = []
    if not_sent:
        listed = [f"Not sent meanwhile ({len(not_sent):,}):", *map(_not_sent_line, not_sent[:MAX_NOT_SENT])]
        if len(not_sent) > MAX_NOT_SENT:
            listed.append(f"+{len(not_sent) - MAX_NOT_SENT:,} more")
    return "\n".join([
        f"✅ <b>Restored</b> · {_escape(_service_name(service))} is responding again",
        f"Down: {_period(since, now)} ({_duration(since, now)}), {attempts:,} failed "
        f"{'attempt' if attempts == 1 else 'attempts'}",
        *listed,
        *_codes(first_code, code),
    ])


def _not_sent_line(entry: dict) -> str:
    """ A Fout on the list Not sent meanwhile, like Bug · Radarr · k7p2qx, with only the service and the Code it has """
    parts = [_escape(str(entry["fault"]).title())]
    if entry["service"]:
        parts.append(_escape(_service_name(entry["service"])))
    if entry["code"]:
        parts.append(f"<code>{_escape(entry['code'])}</code>")
    return " · ".join(parts)


def fixed_html(msg: str, since: datetime, now: datetime, times: int, first_code: str | None,
               code: str | None) -> str:
    """ The Herstelmelding after an Inrichtingsfout was set right, in HTML: what is right now, from when till when
    it went wrong, how often, and the Code of the first admin message → that of the check that succeeded
    """
    return "\n".join([
        f"✅ <b>Fixed</b> · {_escape(msg)}",
        f"Failing: {_period(since, now)} ({_duration(since, now)}), {times:,}×",
        *_codes(first_code, code),
    ])


def _setup_key(service: str, check: str, item: int | str | None) -> str:
    """ What makes two Inrichtingsfouten the same: the service, the check and the item, if it has one """
    return " ".join(str(part) for part in (service, check, item) if part is not None)


def _service_name(service: str) -> str:
    """ The name of a service for a person, like Radarr """
    return SERVICE_NAMES.get(service, service)


def _period(start: datetime, end: datetime) -> str:
    """ From start to end in local time, like 05:02 – 06:07, with the days when they are not both today, the end """
    if start.astimezone().date() == end.astimezone().date():
        return f"{start.astimezone():%H:%M} – {end.astimezone():%H:%M}"
    return f"{_day_and_time(start, end)} – {_day_and_time(end, end)}"


def _duration(start: datetime, end: datetime) -> str:
    """ How long from start to end, in the whole minutes the times show: 45 min, 1 h 5 min, or 33 days """
    minutes = int((end.replace(second=0, microsecond=0) - start.replace(second=0, microsecond=0)).total_seconds()
                  // 60)
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 24 * 60:
        return f"{minutes // 60} h {minutes % 60} min" if minutes % 60 else f"{minutes // 60} h"
    days = minutes // (24 * 60)
    return f"{days} day" if days == 1 else f"{days} days"


def _codes(first: str | None, then: str | None) -> list[str]:
    """ The line Code: of a Herstelmelding, the first Code → the last, with only the Codes there are: outside an
    Interaction there is none. No line without any.
    """
    codes = [f"<code>{_escape(code)}</code>" for code in (first, then) if code]
    return [f"Code: {' → '.join(codes)}"] if codes else []


@dataclass(frozen=True)
class _Piece:
    """ A piece of the expandable block, unescaped, and whether it is code """
    text: str
    code: bool = False

    def html(self) -> str:
        return f"<code>{_escape(self.text)}</code>" if self.code else _escape(self.text)


def _fit(head: list[str], block: list[_Piece], tail: list[str]) -> str:
    """ The message, with as much of the block as fits in one message of Telegram.

    A block that does not fit is cut from the back and ends with TRUNCATED. The cut falls between two characters
    of a piece, so never in a tag or an entity.
    """

    def message(pieces: list[_Piece], cut: bool = False) -> str:
        inner = [piece.html() for piece in pieces] + ([TRUNCATED] if cut else [])
        quote = ["<blockquote expandable>" + "\n".join(inner) + "</blockquote>"] if inner else []
        return "\n".join([*head, *quote, *tail])

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
