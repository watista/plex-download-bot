#!/usr/bin/python3

""" The old Log class as a thin layer on the new logging, until the issues after 01 replace its calls """

import os
import re
import sys
import json
import logging
import asyncio
from telegram import Bot
from telegram.error import TelegramError, RetryAfter

from src.log import ROOT, get_logger


log = get_logger(__name__)

# The old dtype values
LEVELS = {"error": logging.ERROR, "warning": logging.WARNING, "info": logging.INFO}

# The services as the arr clients call themselves, until the request rule of issue 09
SERVICES = {"movie": "radarr", "serie": "sonarr"}


def caller_logger(depth: int):
    """ The logger of the module that called the method this many frames up """
    return get_logger(sys._getframe(depth + 1).f_globals.get("__name__", ROOT))


class Log:

    def __init__(self, args=False):

        # Init Telegram bot
        self.bot = Bot(os.getenv('BOT_TOKEN')) if args.env == "live" else Bot(os.getenv('BOT_TOKEN_DEV'))

        # Set chat_id
        self.own_chatid = os.getenv('CHAT_ID_GROUP') if getattr(args, 'env', 'dev') == "live" else os.getenv('CHAT_ID_ADMIN')


    async def logger(self, msg: str, silent=False, dtype="debug", telegram=True, chat_id=None) -> None:
        """ Write the line to the log file, for the code that called this method, and send it to Telegram """

        # The plain text, without the MarkdownV2 escapes of the Telegram message
        caller_logger(1).log(LEVELS.get(dtype, logging.DEBUG), msg, stacklevel=2)

        # Send telegram message
        if telegram:
            chat_id = self.own_chatid if chat_id is None else chat_id
            await self.send_telegram_message(self.escape_markdown(msg), silent, chat_id)


    async def send_telegram_message(self, msg: str, silent: bool, chat_id: int) -> None:
        """ Send message to Telegram """

        # Split all words on spaces
        words = msg.split(' ')
        messages = []
        current_chunk = ""

        # Loop through all words to create chunks
        for word in words:
            if len(current_chunk) + len(word) + 1 > 1024:
                messages.append(current_chunk)
                # Start a new chunk
                current_chunk = word
            else:
                # Append word to current chunk
                current_chunk += (" " if current_chunk else "") + word

        # Add last chunk if not empty
        if current_chunk:
            messages.append(current_chunk)

        for message in messages:
            while True:
                try:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="MarkdownV2",
                        disable_web_page_preview=False,
                        disable_notification=silent
                    )
                    break
                except RetryAfter as e:
                    await asyncio.sleep(e.retry_after)
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="MarkdownV2",
                        disable_web_page_preview=False,
                        disable_notification=silent
                    )
                    break
                except TelegramError as e:
                    log.error(f"Telegram API error: {e}", exc_info=True)
                    break
                except Exception as e:
                    log.error(f"Unexpected error while sending Telegram message: {e}", exc_info=True)
                    break


    def is_debug(self) -> bool:
        """ Returns True if the log level is DEBUG """
        return logging.getLogger(ROOT).isEnabledFor(logging.DEBUG)


    def truncate(self, value) -> str:
        """ Shorten a request or response body so the log file stays readable """

        # Set max length, LOG_MAX_BODY=0 means no truncating at all
        try:
            max_length = int(os.getenv("LOG_MAX_BODY", "2000"))
        except ValueError:
            max_length = 2000

        # Return the value as string, shortened if needed
        text = value if isinstance(value, str) else str(value)
        if max_length <= 0 or len(text) <= max_length:
            return text
        return f"{text[:max_length]}... [truncated, {len(text)} chars total]"


    async def debug_call(self, service: str, action: str, **details) -> None:
        """ Write a request or its response as an http_call line on DEBUG, for the code that called this method """

        # Skip the work completely when not debugging
        if not self.is_debug():
            return

        # The fields of an http_call from the given details
        service = SERVICES.get(service, service)
        method = action.split(" ")[0]
        fields = {"method": method} if method in ("GET", "POST", "PUT", "DELETE") else {}
        for key, value in details.items():
            if key == "duration" and value is not None:
                fields["duration_ms"] = round(value * 1000)
            elif key == "status":
                fields["http_status"] = value
            elif key in ("payload", "response") and value is not None:
                body = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
                fields["request" if key == "payload" else "response"] = self.truncate(body)
            else:
                fields[key] = value

        caller_logger(1).debug(f"{service} {action}", event="http_call", service=service, stacklevel=2, **fields)


    def escape_markdown(self, text: str) -> str:
        """ Escape reserverd characters for Markdown V2 """
        special_chars = r'_\[\]()~`>#+-=|{}.!'
        return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)
