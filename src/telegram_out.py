#!/usr/bin/python3

""" Verzendfunctie: the one way the bot itself sends a message to Telegram """

import html
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from telegram import Bot, LinkPreviewOptions
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError

from src.faults import Fault, FaultKind
from src.log import get_logger, mask


log = get_logger(__name__)

# The most characters Telegram takes in one message
MAX_LENGTH = 4096

# How a BadRequest starts when Telegram rejects the formatting, in lower case
REJECTED_FORMATTING = ("can't parse entities", "can't parse message text")


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

    async def send(self, chat_id: int | str, text: str, fmt: str | None, silent: bool = False) -> Delivery:
        """ Sends text in fmt: HTML, MarkdownV2 or None for plain text.

        The secrets are masked and the text is cut at 4096 characters. When Telegram rejects the
        formatting, the text goes once more as plain text, with the rejection on top. That rejection is a
        Bug, which gets a line but no admin message of its own.
        """
        try:
            return await self._attempt(chat_id, text, fmt, silent)
        except BadRequest as e:
            if not rejects_formatting(e):
                raise
            rejection = e.message
            log.error(f"Telegram rejected the {fmt} formatting of a message: {rejection}", exc_info=e,
                      reason=rejection, fault=FaultKind.BUG, service="telegram")

        try:
            return await self._attempt(chat_id, f"⚠️ Telegram rejected the formatting: {rejection}\n\n"
                                                f"{plain_text(text, fmt)}", None, silent)
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
        arrive is a WARNING with the reason. A Fault of Telegram falls through.
        """
        user_id = int(user_id)
        account = await self._account_for(user_id)
        delivery = await self.send(user_id, text, "HTML")
        about = f" about {media.get('title')} ({media.get('year')})" if media else ""
        if delivery.delivered:
            log.info(f"sent user message {kind}{about}", user_id=user_id, account=account, event="user_message",
                     kind=kind, media=media)
        else:
            log.warning(f"user message {kind}{about} not delivered: {delivery.reason}", user_id=user_id,
                        account=account, event="user_message", kind=kind, reason=delivery.reason, media=media)
        return delivery

    async def _attempt(self, chat_id: int | str, text: str, fmt: str | None, silent: bool) -> Delivery:
        """ One attempt to send the text, with its secrets masked and cut at 4096 characters.

        Telegram not responding is a Storing, and a message it does not deliver (blocked by the user) is not a Fout.
        """
        try:
            await self._bot.send_message(chat_id=chat_id, text=mask(text)[:MAX_LENGTH], parse_mode=fmt,
                                         disable_notification=silent,
                                         link_preview_options=LinkPreviewOptions(is_disabled=True))
        except Forbidden as e:
            return Delivery(e.message)
        except TelegramError as e:
            if (fault := telegram_disruption(e)) is None:
                raise
            raise fault from e
        return DELIVERED
