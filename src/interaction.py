#!/usr/bin/python3

""" Interactie: one update or one run of a job, with a Code that every line of it carries """

import asyncio
import functools
import html
import json
import secrets
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field, replace
from time import monotonic
from typing import TYPE_CHECKING, Any, TypeVar

import aiofiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, User
from telegram.error import TelegramError
from telegram.ext import BaseUpdateProcessor, CallbackContext, ConversationHandler, JobQueue

from src.log import get_logger

if TYPE_CHECKING:
    # Only for the types: src.faults and src.telegram_out import this module, so the wrappers import them when they run
    from src.faults import Fault, FaultReporter
    from src.telegram_out import Delivery


log = get_logger(__name__)

T = TypeVar("T")

# The verzendfunctie: send(chat_id, text, fmt, silent=False)
Send = Callable[..., Awaitable["Delivery"]]


# The characters of a Code: no 0 o 1 l i, which look alike
ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
CODE_LENGTH = 6

# The seconds after a Bug in the heartbeat before guard_task starts it again
RESTART_AFTER = 60


@dataclass(frozen=True)
class Interaction:
    """ The context of an Interaction.

    Its Code, the person of an update or the name of a job, the media item it is working on (working_on), which only
    the meldfunctie reads, and the counts of a run (tally), which only guard_job reads.
    """
    code: str
    user_id: int | None = None
    account: str | None = None
    tg_name: str | None = None
    job: str | None = None
    media: dict | None = field(default=None, compare=False)
    # Changed in place, so working_on keeps them, and a task that the run started counts for the run
    counts: dict[str, int] = field(default_factory=dict, compare=False)


# The Interaction that the current code runs in, None outside one (start, polling, the heartbeat)
_current: ContextVar[Interaction | None] = ContextVar("interaction", default=None)


def new_code() -> str:
    """ A new Code: 6 random characters of the alphabet, like k7p2qx """
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def current_code() -> str | None:
    """ The Code of the current Interaction, None outside one """
    interaction = _current.get()
    return interaction.code if interaction else None


def current_interaction() -> Interaction | None:
    """ The current Interaction, None outside one """
    return _current.get()


def working_on(media: dict | None) -> None:
    """ Sets the media item the current Interaction is working on, which the meldfunctie takes when a Fault has none.

    A job with a loop sets it per item. Outside an Interaction there is no context to set it in.
    """
    interaction = _current.get()
    if interaction is not None:
        _current.set(replace(interaction, media=media))


def tally(name: str, n: int = 1) -> None:
    """ Counts n for name in the current Interaction, for the line job_finished at the end of a run.

    Outside an Interaction there is nothing to count for. In an update the count goes nowhere: only a run ends with a
    line.
    """
    interaction = _current.get()
    if interaction is not None:
        interaction.counts[name] = interaction.counts.get(name, 0) + n


async def account_for(user_id: int, data_json: str) -> str | None:
    """ The account name of a user ID in the user list of data.json, None for a Bezoeker.

    data.json is read on every call, so a Bezoeker who just logged in is a Gebruiker from the next update on.
    """
    async with aiofiles.open(data_json, "r") as file:
        data = json.loads(await file.read())
    return account_in(data, user_id)


def account_in(data: dict, user_id: int | str) -> str | None:
    """ The account name of a user ID in the user list of data, the contents of data.json; None for a Bezoeker.

    The user list holds "account name, Telegram name" per user ID. A blocked user ID is a Bezoeker,
    also when it is still in the user list.
    """
    if str(user_id) in data.get("blocked_users", {}):
        return None
    entry = data.get("user_id", {}).get(str(user_id))
    if not entry:
        return None
    return entry.split(",", 1)[0].strip() or None


async def person_fields(user: User, account_for: Callable[[int], Awaitable[str | None]]) -> dict:
    """ Who a Telegram user is in a line: a Gebruiker by account name, a Bezoeker by Telegram name.

    Empty when the user list cannot be read, so the line is written anyway, without guessing who it is.
    """
    try:
        account = await account_for(user.id)
    except Exception:
        log.error(f"could not look up the account of user {user.id}", exc_info=True)
        return {}
    if account:
        return {"account": account}
    # The Telegram name only for a Bezoeker, so a Bezoeker never shows up under the account name of a Gebruiker
    return {"tg_name": user.first_name}


def context_fields() -> dict:
    """ The fields that every line in the current Interaction gets, also a line of a library; empty outside one """
    interaction = _current.get()
    if interaction is None:
        return {}
    fields = {
        "user_id": interaction.user_id,
        "account": interaction.account,
        "tg_name": interaction.tg_name,
        "interaction_id": interaction.code,
        "job": interaction.job,
    }
    return {key: value for key, value in fields.items() if value is not None}


class InteractionProcessor(BaseUpdateProcessor):
    """ Handles each update as an Interaction: a new Code, and the person who sent it.

    Set with ApplicationBuilder.concurrent_updates(InteractionProcessor(1, ...)), so the updates are
    still handled one by one. account_for gives the account name of a user ID, None for a Bezoeker.
    """

    def __init__(self, max_concurrent_updates: int, account_for: Callable[[int], Awaitable[str | None]]):
        super().__init__(max_concurrent_updates)
        self._account_for = account_for

    async def do_process_update(self, update: object, coroutine: Awaitable[Any]) -> None:
        user = update.effective_user if isinstance(update, Update) else None
        token = _current.set(Interaction(new_code(), user_id=user.id if user else None))
        try:
            if user:
                # Never raises: an exception here would stop the update fetcher of PTB, and with it every
                # update after this one
                _current.set(replace(_current.get(), **await person_fields(user, self._account_for)))
            await coroutine
        finally:
            # Without the reset the context leaks into the next update
            _current.reset(token)

    async def initialize(self) -> None:
        """ Nothing to set up """

    async def shutdown(self) -> None:
        """ Nothing to free """


class SchedulerOutsideInteractions(AsyncIOScheduler):
    """ An AsyncIOScheduler that always wakes up outside an Interaction.

    The scheduler runs in the context of whoever woke it last: a job added during an update, like the
    timeout of a conversation, would otherwise give the lines of the scheduler and every job it starts
    afterwards the context of that update.
    """

    def wakeup(self) -> None:
        # The rest of the context stays as it is; only the Interaction goes
        context = copy_context()
        context.run(_current.set, None)
        context.run(super().wakeup)


class JobQueueOutsideInteractions(JobQueue):
    """ The JobQueue of PTB with a scheduler outside every Interaction: set with ApplicationBuilder.job_queue() """

    def __init__(self) -> None:
        super().__init__()
        self.scheduler = SchedulerOutsideInteractions(**self.scheduler_configuration)


def guard(callback: Callable[[Update, CallbackContext], Awaitable[T]], faults: "FaultReporter",
          send: Send) -> Callable[[Update, CallbackContext], Awaitable[T | int]]:
    """ Wraps the callback of a handler when it is registered: a Fout in it ends the Gesprek with a Foutmelding.

    Every exception is a Fout: a Fault as it is, Telegram not responding as a Storing of Telegram, and anything else
    as a Bug. The wrapper reports it to faults, the meldfunctie, and then sends the Foutmelding through send, the
    verzendfunctie. While Telegram is not responding it does not try. After a Fout it always gives back
    ConversationHandler.END, also for a stand-alone handler, whose answer PTB ignores.
    """

    @functools.wraps(callback)
    async def guarded(update: Update, context: CallbackContext) -> T | int:
        try:
            return await callback(update, context)
        except Exception as error:
            await _report_and_tell(_as_fault(_without_wrapper_frame(error)), update, faults, send)
            return ConversationHandler.END

    return guarded


def guard_job(callback: Callable[[CallbackContext], Awaitable[T]], faults: "FaultReporter",
              counts: dict[str, str | None] | None = None,
              done: str | None = None) -> Callable[[CallbackContext], Awaitable[T | None]]:
    """ Runs every run of a job as an Interaction of its own: a new Code and the name of the job, no person.

    Wraps the callback when the job is registered, with its name: run_repeating(guard_job(callback, faults), ...,
    name=...). A Fout stops the run and goes to faults, the meldfunctie, like in guard. A job tells no one, so there
    is no Foutmelding.

    Every run ends with the line job_finished, also a run that a Fout stopped: whether it finished, how long it took,
    and what it counted with tally until then. counts names the counts of the job, each with how msg says it, like
    {"items": "{n} item{s} checked"}, or None to keep it to its field; a count the run did not keep is 0. done is
    what msg says after a run that finished, like "Transmission reachable".
    """

    @functools.wraps(callback)
    async def guarded(context: CallbackContext) -> T | None:
        # Set here, not inherited: a job only gets the context its scheduler runs in, at best none.
        # No reset afterwards: PTB runs every job in a task of its own, so this context ends with the run,
        # and the error_handler that PTB starts from that task after an exception still gets it.
        run = Interaction(new_code(), job=context.job.name)
        _current.set(run)
        started = monotonic()
        finished = False
        try:
            result = await callback(context)
            finished = True
            return result
        except Exception as error:
            await faults.report(_as_fault(_without_wrapper_frame(error)))
            return None
        finally:
            _job_finished(run, monotonic() - started, finished, counts or {}, done)

    return guarded


def _job_finished(run: Interaction, seconds: float, finished: bool, counts: dict[str, str | None],
                  done: str | None) -> None:
    """ The last line of a run, like "check_notify_list finished in 4.2 s: 14 items checked, 2 messages sent" """
    duration_ms = round(seconds * 1000)
    values = {name: run.counts.get(name, 0) for name in counts} | run.counts
    summary = [phrase.format(n=values[name], s="" if values[name] == 1 else "s")
               for name, phrase in counts.items() if phrase is not None]
    if finished and done:
        summary.append(done)
    took = f"finished in {duration_ms / 1000:.1f} s" if finished else f"stopped after {duration_ms / 1000:.1f} s"
    log.info(f"{run.job} {took}" + (f": {', '.join(summary)}" if summary else ""), event="job_finished",
             outcome="ok" if finished else "stopped", duration_ms=duration_ms, **values)


async def guard_task(coro_fn: Callable[[], Awaitable[None]], faults: "FaultReporter",
                     sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """ Runs coro_fn, the heartbeat, which is no handler and no job: asyncio.create_task(guard_task(...)).

    A Fout in it goes to faults, the meldfunctie, like in guard: any exception but a Fault is a Bug. It is outside an
    Interaction, so a Bug gets a Code of its own there. RESTART_AFTER seconds later coro_fn starts again, because
    without the heartbeat the watcher takes the home server for down and starts the fallback bot, and then two bots
    poll. The throttle of a Bug keeps one that comes back at one admin message per 24 hours. When coro_fn ends by
    itself, so does this.
    """
    while True:
        try:
            await coro_fn()
            return
        except Exception as error:
            await faults.report(_as_fault(_without_wrapper_frame(error)))
        await sleep(RESTART_AFTER)


async def report_outside_wrapper(update: object, error: Exception, faults: "FaultReporter", send: Send) -> None:
    """ What error_handler does with an exception that no wrapper caught: a Fout, reported as caught outside the wrapper.

    error_handler cannot end a Gesprek. It only sends a Foutmelding when there is an update with a chat.
    """
    await _report_and_tell(_as_fault(error), update, faults, send, outside_wrapper=True)


def _without_wrapper_frame(error: Exception) -> Exception:
    """ The exception, changed in place, without the frame of the wrapper that caught it: the Fout is that of the
    callback. An exception of the wrapper itself, like a callback that gives back no coroutine, keeps its frame. """
    traceback = error.__traceback__
    return error.with_traceback(traceback.tb_next) if traceback and traceback.tb_next else error


def _as_fault(error: Exception) -> "Fault":
    """ The Fout that an exception is, by faults.as_fault: imported when a wrapper runs, as src.faults imports this
    module """
    from src.faults import as_fault

    return as_fault(error)


async def _report_and_tell(fault: "Fault", update: object, faults: "FaultReporter", send: Send,
                           outside_wrapper: bool = False) -> None:
    """ Reports the Fout, and then tells the user in a Foutmelding when there is someone to tell.

    First the report, so the Foutmelding never promises an admin message that did not go out. There is no one to tell
    without a chat, or outside an Interaction (the timeout of a Gesprek), where there is no Code to give. While
    Telegram is not responding there is no telling at all.
    """
    from src.faults import FaultKind

    chat = update.effective_chat if isinstance(update, Update) else None
    code = current_code()
    telegram_down = fault.kind == FaultKind.DISRUPTION and fault.service == "telegram"
    tell = chat is not None and code is not None and not telegram_down
    known = await faults.report(fault, user_told=tell, outside_wrapper=outside_wrapper)
    if tell:
        await _send_error_message(chat.id, _error_message(fault, known, code), faults, send)


# The first line of a Foutmelding per kind of Fout (as in the field fault), when the Fault has no user_text
SENTENCES = {
    "bug": "Oeps, daar ging iets fout",
    "disruption": "Een onderdeel van de Plęx server reageert op dit moment niet",
    "setup": "Er is een probleem met de inrichting van de Plęx server",
}


def _error_message(fault: "Fault", known: bool, code: str) -> str:
    """ The Foutmelding, in HTML: what went wrong, whether the Beheerder knows, how to go on, and the Code.

    known is what report() gave back: whether an admin message about this Fout went out, now or earlier.
    """
    what = html.escape(fault.user_text or SENTENCES[fault.kind], quote=False)
    then = "De serverbeheerder is hiervan op de hoogte." if known else "Probeer het later nog eens."
    return f"<b>😵 {what}</b>\n\n{then} Stuur /start om opnieuw te beginnen.\n\nCode: <code>{code}</code>"


async def _send_error_message(chat_id: int, text: str, faults: "FaultReporter", send: Send) -> None:
    """ Sends the Foutmelding. One that does not arrive is only in the log: Telegram not responding as an attempt
    of a Storing of Telegram, anything else as a WARNING with the reason """
    from src.faults import Fault

    try:
        reason = (await send(chat_id, text, "HTML")).reason
    except Fault as unsent:
        await faults.report(unsent)
        return
    except TelegramError as e:
        # Telegram did answer, but not with the message
        reason = e.message
    if reason is not None:
        log.warning(f"error message not delivered: {reason}", reason=reason)
