#!/usr/bin/python3

""" Interactie: one update or one run of a job, with a Code that every line of it carries """

import functools
import json
import secrets
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, replace
from typing import Any, TypeVar

import aiofiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, User
from telegram.ext import BaseUpdateProcessor, CallbackContext, JobQueue

from src.log import get_logger


log = get_logger(__name__)

T = TypeVar("T")


# The characters of a Code: no 0 o 1 l i, which look alike
ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
CODE_LENGTH = 6


@dataclass(frozen=True)
class Interaction:
    """ The context of an Interaction: its Code, and the person of an update or the name of a job """
    code: str
    user_id: int | None = None
    account: str | None = None
    tg_name: str | None = None
    job: str | None = None


# The Interaction that the current code runs in, None outside one (start, polling, the heartbeat)
_current: ContextVar[Interaction | None] = ContextVar("interaction", default=None)


def new_code() -> str:
    """ A new Code: 6 random characters of the alphabet, like k7p2qx """
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def current_code() -> str | None:
    """ The Code of the current Interaction, None outside one """
    interaction = _current.get()
    return interaction.code if interaction else None


async def account_for(user_id: int, data_json: str) -> str | None:
    """ The account name of a user ID in the user list of data.json, None for a Bezoeker.

    The user list holds "account name, Telegram name" per user ID. A blocked user ID is a Bezoeker,
    also when it is still in the user list. data.json is read on every call, so a Bezoeker who just
    logged in is a Gebruiker from the next update on.
    """
    async with aiofiles.open(data_json, "r") as file:
        data = json.loads(await file.read())
    if str(user_id) in data.get("blocked_users", {}):
        return None
    entry = data.get("user_id", {}).get(str(user_id))
    if not entry:
        return None
    return entry.split(",", 1)[0].strip() or None


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
                _current.set(replace(_current.get(), **await self._person(user)))
            await coroutine
        finally:
            # Without the reset the context leaks into the next update
            _current.reset(token)

    async def _person(self, user: User) -> dict:
        """ A Gebruiker by account name, a Bezoeker by Telegram name """
        try:
            account = await self._account_for(user.id)
        except Exception:
            # Handle the update anyway, without guessing who it is. An exception here would stop the
            # update fetcher of PTB, and with it every update after this one.
            log.error(f"could not look up the account of user {user.id}", exc_info=True)
            return {}
        if account:
            return {"account": account}
        # The Telegram name only for a Bezoeker, so a Bezoeker never shows up under the account name of a Gebruiker
        return {"tg_name": user.first_name}

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


def guard_job(callback: Callable[[CallbackContext], Awaitable[T]]) -> Callable[[CallbackContext], Awaitable[T]]:
    """ Runs every run of a job as an Interaction of its own: a new Code and the name of the job, no person.

    Wraps the callback when the job is registered, with its name: run_repeating(guard_job(callback), ..., name=...).
    """

    @functools.wraps(callback)
    async def guarded(context: CallbackContext) -> T:
        # Set here, not inherited: a job only gets the context its scheduler runs in, at best none.
        # No reset afterwards: PTB runs every job in a task of its own, so this context ends with the run,
        # and the error_handler that PTB starts from that task after an exception still gets it.
        _current.set(Interaction(new_code(), job=context.job.name))
        return await callback(context)

    return guarded
