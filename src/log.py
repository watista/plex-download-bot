#!/usr/bin/python3

import os
import re
import logging
import time
import asyncio
from pathlib import Path
from telegram import Bot
from telegram.error import TelegramError, RetryAfter


# Libraries that log on every poll cycle when DEBUG is enabled (getUpdates
# calls, HTTP internals, connection handling). Below WARNING these only go to
# the separate debug log file, so they can't drown out the bot's own messages.
NOISY_LOGGERS = (
    "httpcore",
    "httpx",
    "telegram",
    "urllib3",
    "asyncio",
    "aiohttp",
    "apscheduler",
    "charset_normalizer",
)


class NoLibraryChatter(logging.Filter):
    """ Drop third party DEBUG/INFO records, keep their warnings and errors """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        return not record.name.startswith(NOISY_LOGGERS)


class Log:

    def __init__(self, args=False):

        # Init Telegram bot
        self.bot = Bot(os.getenv('BOT_TOKEN')) if args.env == "live" else Bot(os.getenv('BOT_TOKEN_DEV'))

        # Set logging format and config
        logging.root.handlers = []
        log_level = os.getenv('LOG_TYPE', 'INFO').upper()
        logging_level = getattr(logging, log_level, logging.INFO)
        debug_mode = logging_level <= logging.DEBUG

        fmt = "%(asctime)s - %(levelname)s - %(name)s: %(message)s"
        detailed_fmt = fmt + " - {%(pathname)s - %(module)s - %(funcName)s - %(lineno)d}"
        datefmt = '%d-%m-%Y %H:%M:%S'

        # Outside debug mode there is no debug file catching the chatter, so
        # silence httpx (every GET and POST) and apscheduler (every executed
        # schedule task) at the source
        if not debug_mode:
            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("apscheduler").setLevel(logging.WARNING)

        # Set name and create the log file and folder if not exist
        log_folder = os.getenv("LOG_FOLDER", "log")
        file_name = "wouter-thuisserver-bot" if args.env == "live" else "dev-wouter-thuisserver-bot"
        base_name = f"{log_folder}/{file_name}-{time.strftime('%m-%d-%Y')}"
        log_file = f"{base_name}.log"
        Path(log_folder).mkdir(parents=True, exist_ok=True)
        Path(log_file).touch(exist_ok=True)

        # Setup the logging config
        logging.root.setLevel(logging_level)

        # Main log file, on DEBUG without the third party polling noise
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging_level)
        file_handler.setFormatter(logging.Formatter(detailed_fmt if debug_mode else fmt, datefmt))
        if debug_mode:
            file_handler.addFilter(NoLibraryChatter())
        logging.root.addHandler(file_handler)

        # On DEBUG everything, library chatter included, also goes to a
        # separate file so the main log stays readable
        if debug_mode:
            debug_file = f"{base_name}-debug.log"
            Path(debug_file).touch(exist_ok=True)
            debug_handler = logging.FileHandler(debug_file)
            debug_handler.setLevel(logging.DEBUG)
            debug_handler.setFormatter(logging.Formatter(detailed_fmt, datefmt))
            logging.root.addHandler(debug_handler)

        # Set console logging
        if args.verbose:
            console = logging.StreamHandler()
            console.setLevel(logging_level)
            console.setFormatter(logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S"))
            if debug_mode:
                console.addFilter(NoLibraryChatter())
            logging.root.addHandler(console)

        # Set chat_id
        self.own_chatid = os.getenv('CHAT_ID_GROUP') if getattr(args, 'env', 'dev') == "live" else os.getenv('CHAT_ID_ADMIN')


    async def logger(self, msg: str, silent=False, dtype="debug", telegram=True, chat_id=None) -> None:
        """ Send the log message to telegram and/or the log file """

        # Set chat_id
        chat_id = self.own_chatid if chat_id is None else chat_id

        # Send telegram message
        if telegram:
            msg = self.escape_markdown(msg)
            await self.send_telegram_message(msg, silent, chat_id)

        # Prettify log message for file logging
        cleaned_msg = self.clean_message(msg)

        # Log to file based on type
        self.log_to_file(cleaned_msg, dtype)


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
                    logging.error(f"Telegram API error: {e}", exc_info=True)
                    break
                except Exception as e:
                    logging.error(f"Unexpected error while sending Telegram message: {e}", exc_info=True)
                    break


    def is_debug(self) -> bool:
        """ Returns True if the log level is DEBUG """
        return logging.getLogger().isEnabledFor(logging.DEBUG)


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
        """ Log a request and its response to file, only when the log level is DEBUG """

        # Skip the work completely when not debugging
        if not self.is_debug():
            return

        # Build the message from the given details
        parts = [f"{service} {action}"]
        for key, value in details.items():
            if value is None:
                continue
            if key == "duration":
                parts.append(f"duration: {value:.2f}s")
            else:
                parts.append(f"{key}: {self.truncate(value)}")

        await self.logger(" | ".join(parts), False, "debug", False)


    def clean_message(self, msg: str) -> str:
        """ Sanitize the log message to avoid formatting issues """
        msg = msg.encode('ascii', 'ignore').decode('ascii')
        msg = msg.replace("\n", " - ").replace("*", "").replace("`", "").replace("  ", " ").strip()
        return msg


    def log_to_file(self, msg: str, dtype: str) -> None:
        """ Log messages to a file based on the type """
        match dtype:
            case "error":
                logging.error(msg)
            case "warning":
                logging.warning(msg)
            case "info":
                logging.info(msg)
            case _:
                logging.debug(msg)


    def escape_markdown(self, text: str) -> str:
        """ Escape reserverd characters for Markdown V2 """
        special_chars = r'_\[\]()~`>#+-=|{}.!'
        return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)
