#!/usr/bin/python3

""" Verzendfunctie: the one way the bot itself sends a message to Telegram """

import html
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic

from telegram import Bot, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.request import HTTPXRequest, RequestData

from src.faults import Fault, FaultKind, FaultReporter
from src.interaction import Send, tally
from src.log import get_logger, mask


log = get_logger(__name__)

# The most characters Telegram takes in one message
MAX_LENGTH = 4096

# How a BadRequest starts when Telegram rejects the formatting, in lower case
REJECTED_FORMATTING = ("can't parse entities", "can't parse message text")

# The method of the Bot API that polls, which gets no http_call
POLLING = "getUpdates"

# The token of the bot in the url of a request, after /bot
WITH_TOKEN = re.compile(r"(/bot)[^/]+")

# The seconds that the new Bot of a crash waits for Telegram, per step of a request
CRASH_TIMEOUT = 5


@dataclass(frozen=True)
class Delivery:
    """ Whether Telegram delivered a message: reason says why not, None when it did """
    reason: str | None = None

    @property
    def delivered(self) -> bool:
        return self.reason is None


DELIVERED = Delivery()


def telegram_disruption(error: BaseException) -> Fault | None:
    """ The Storing of Telegram that an exception of PTB stands for, None for any other exception.

    A NetworkError (TimedOut is one) or RetryAfter means Telegram is not responding; the bot does not wait for
    RetryAfter. A BadRequest is a NetworkError too, but then Telegram did answer. The caller raises the Fault from
    the error, or sets it as its cause.
    """
    if isinstance(error, (NetworkError, RetryAfter)) and not isinstance(error, BadRequest):
        return Fault.disruption(service="telegram", what="Telegram is not responding", reason=str(error))
    return None


def length(text: str) -> int:
    """ The length of a text as Telegram counts it: in UTF-16, so an emoji counts two """
    return len(text.encode("utf-16-le")) // 2


def cut(text: str) -> str:
    """ The text cut at the 4096 characters that Telegram takes, as it counts them, without cutting a character in
    half """
    if length(text) <= MAX_LENGTH:
        return text
    return text.encode("utf-16-le")[:2 * MAX_LENGTH].decode("utf-16-le", errors="ignore")


def rejects_formatting(error: BadRequest) -> bool:
    """ True when Telegram refused a message because it could not parse its HTML or MarkdownV2 """
    return error.message.lower().startswith(REJECTED_FORMATTING)


def escape_markdown(text: str) -> str:
    """ Escapes the reserved characters of MarkdownV2, except * so *bold* stays bold """
    return re.sub(r"([_\[\]()~`>#+\-=|{}.!])", r"\\\1", text)


def plain_text(text: str, fmt: str | None) -> str:
    """ The text without its formatting: HTML without tags and with its entities back, MarkdownV2 without escapes """
    if fmt == "HTML":
        return html.unescape(re.sub(r"<[^>]*>", "", text))
    if fmt == "MarkdownV2":
        return re.sub(r"\\(.)", r"\1", text, flags=re.DOTALL)
    return text


class TelegramRequest(HTTPXRequest):
    """ The requests of the bot to Telegram: set with ApplicationBuilder.request() and .get_updates_request().

    Every successful answer ends a Storing of Telegram in faults, the meldfunctie, also an answer to polling: so the
    Herstelmelding after a Storing in the night comes at once, not with the next message. A failed attempt is not
    counted here, because PTB has to see its own exceptions to try again: it is counted where it comes up, in
    error_handler (polling), the wrapper and the verzendfunctie.

    faults is given after the bot is built: the meldfunctie needs the verzendfunctie, which needs the bot, which is
    built with this request. Until then an answer only goes to PTB.

    Every request but getUpdates, which polls every few seconds, gets an http_call on DEBUG. It has the method, the
    url without the token, the status and the duration, but not the request and the response: those hold the text
    of messages, like a password or the e-mail and phone of an account request.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.faults: FaultReporter | None = None

    async def do_request(self, url: str, method: str, request_data: RequestData | None = None,
                         **timeouts) -> tuple[int, bytes]:
        endpoint = url.rsplit("/", 1)[-1]
        started = monotonic()
        try:
            status, payload = await super().do_request(url, method, request_data, **timeouts)
        except Exception as error:
            if endpoint != POLLING:
                _http_call(endpoint, method, url, started, error=error)
            raise
        if endpoint != POLLING:
            _http_call(endpoint, method, url, started, status=status)
        if 200 <= status < 300 and self.faults is not None:
            await self._ok()
        return status, payload

    async def _ok(self) -> None:
        """ Ends a Storing of Telegram. A Fout in that is a Bug that does not reach PTB: PTB would make a NetworkError
        of it, a Storing of Telegram that no successful answer could end.
        """
        try:
            await self.faults.ok("telegram")
        except Exception as error:
            fault = Fault.bug(what="Ending the Storing of Telegram failed")
            fault.__cause__ = error
            await self.faults.report(fault, continued="gave PTB the answer of Telegram")


def _http_call(endpoint: str, method: str, url: str, started: float, status: int | None = None,
               error: Exception | None = None) -> None:
    """ The line of one request to Telegram, on DEBUG: the status, or the exception it ended in """
    duration_ms = round((monotonic() - started) * 1000)
    if not log.enabled_for(logging.DEBUG):
        return
    url = WITH_TOKEN.sub(r"\1***", url)
    if error is None:
        outcome = f"HTTP {status}"
    else:
        outcome = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
    log.debug(f"telegram {endpoint}: {method} {url}: {outcome} in {duration_ms} ms", event="http_call",
              service="telegram", method=method, url=url, http_status=status, duration_ms=duration_ms,
              exc_type=type(error).__name__ if error is not None else None)


class TelegramOut:
    """ Sends the messages of the bot itself: admin messages, Gebruikersberichten and the Foutmelding.

    The plain answers in a Gesprek (Functions.send_message) stay outside it. bot is the bot of the
    Application, admin_chat_id the chat of the Beheerder, and account_for gives the account name of a
    user ID, None for a Bezoeker.
    """

    def __init__(self, bot: Bot, admin_chat_id: int | str, account_for: Callable[[int], Awaitable[str | None]]):
        self._bot = bot
        self._admin_chat_id = admin_chat_id
        self._account_for = account_for

    async def send(self, chat_id: int | str, text: str, fmt: str | None, silent: bool = False,
                   markup: InlineKeyboardMarkup | None = None, edit: int | None = None) -> Delivery:
        """ Sends text in fmt: HTML, MarkdownV2 or None for plain text.

        The secrets are masked and the text is cut at 4096 characters. When Telegram rejects the
        formatting, the text goes once more as plain text, with the rejection on top. That rejection is a
        Bug, which gets a line but no admin message of its own.

        markup holds the buttons under the message. With edit, the ID of a message of the bot in that chat,
        the text goes in place of that message, as after a press on one of its buttons.
        """
        try:
            return await self._attempt(chat_id, text, fmt, silent, markup, edit)
        except BadRequest as e:
            if not rejects_formatting(e):
                raise
            rejection = e.message
            log.error(f"Telegram rejected the {fmt} formatting of a message: {rejection}", exc_info=e,
                      reason=rejection, fault=FaultKind.BUG, service="telegram")

        try:
            return await self._attempt(chat_id, f"⚠️ Telegram rejected the formatting: {rejection}\n\n"
                                                f"{plain_text(text, fmt)}", None, silent, markup, edit)
        except BadRequest as e:
            # Nothing left to try: it stays with the line of the rejection, and the caller hears why
            return Delivery(e.message)

    async def send_admin_message(self, text: str, about: str) -> Delivery:
        """ Sends a message to the Beheerder that is not about a Fout, like "User notified" or "Bot gestart".

        text is MarkdownV2 with *bold*; the other reserved characters are escaped here. The line
        admin_message_sent says what the message was about, but not its text.
        """
        delivery = await self.send(self._admin_chat_id, escape_markdown(text), "MarkdownV2")
        if delivery.delivered:
            log.info(f"admin message sent: {about}", event="admin_message_sent")
        else:
            log.warning(f"admin message not delivered: {about}: {delivery.reason}", reason=delivery.reason)
        return delivery

    async def send_user_message(self, user_id: int | str, kind: str, text: str, media: dict | None = None) -> Delivery:
        """ Sends a Gebruikersbericht in HTML, and writes the line user_message with its receiver.

        kind is online, new_season, new_episodes, message or broadcast, and media the item it is about. The
        line has the user_id and account of the receiver, also in a run of a job, but not the text: that of
        a message or broadcast is in the line admin_command of the Beheerder already. A message that does not
        arrive is a WARNING with the reason. Both count for a run, as sent or not_delivered. A Fault of Telegram
        falls through, and counts as neither.
        """
        user_id = int(user_id)
        account = await self._account_for(user_id)
        delivery = await self.send(user_id, text, "HTML")
        about = f" about {media.get('title')} ({media.get('year')})" if media else ""
        if delivery.delivered:
            log.info(f"sent user message {kind}{about}", user_id=user_id, account=account, event="user_message",
                     kind=kind, media=media)
            tally("sent")
        else:
            log.warning(f"user message {kind}{about} not delivered: {delivery.reason}", user_id=user_id,
                        account=account, event="user_message", kind=kind, reason=delivery.reason, media=media)
            tally("not_delivered")
        return delivery

    @classmethod
    @asynccontextmanager
    async def on_new_bot(cls, token: str, admin_chat_id: int | str,
                         account_for: Callable[[int], Awaitable[str | None]]) -> AsyncIterator[Send]:
        """ The verzendfunctie on a new Bot, for the report of a crash: by then run_polling has shut down the Bot of
        the Application, and closed its event loop.

        The new Bot waits CRASH_TIMEOUT seconds for Telegram at each step of a request (a free connection, connect,
        write and read), so a crash does not keep the bot from stopping. Telegram not responding in that time is a
        Storing of Telegram, as always. The new Bot never polls, so its one request does both, and is closed after.
        """
        async with TelegramRequest(connect_timeout=CRASH_TIMEOUT, read_timeout=CRASH_TIMEOUT,
                                   write_timeout=CRASH_TIMEOUT, pool_timeout=CRASH_TIMEOUT) as request:
            yield cls(Bot(token, request=request, get_updates_request=request), admin_chat_id, account_for).send

    async def _attempt(self, chat_id: int | str, text: str, fmt: str | None, silent: bool,
                       markup: InlineKeyboardMarkup | None, edit: int | None) -> Delivery:
        """ One attempt to send the text, or to put it in place of message edit, with its secrets masked and cut at
        4096 characters.

        Telegram not responding is a Storing, and a message it does not deliver (blocked by the user) is not a Fout.
        """
        text = cut(mask(text))
        no_preview = LinkPreviewOptions(is_disabled=True)
        try:
            if edit is None:
                await self._bot.send_message(chat_id=chat_id, text=text, parse_mode=fmt, disable_notification=silent,
                                             reply_markup=markup, link_preview_options=no_preview)
            else:
                await self._bot.edit_message_text(text=text, chat_id=chat_id, message_id=edit, parse_mode=fmt,
                                                  reply_markup=markup, link_preview_options=no_preview)
        except Forbidden as e:
            return Delivery(e.message)
        except TelegramError as e:
            if (fault := telegram_disruption(e)) is None:
                raise
            raise fault from e
        return DELIVERED
