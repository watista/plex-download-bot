#!/usr/bin/python3

import os
import re
import logging
import time
from pathlib import Path
from telegram import Bot
from telegram.error import TelegramError, RetryAfter


class Log:

    def __init__(self, args=False):

        # Init Telegram bot
        self.bot = Bot(os.getenv('BOT_TOKEN')) if args.env == "live" else Bot(os.getenv('BOT_TOKEN_DEV'))

        # Set logging format and config
        logging.root.handlers = []
        log_level = os.getenv('LOG_TYPE', 'INFO').upper()

        # set higher logging level for httpx to avoid all GET and POST requests being logged and apscheduler to avoid every executed schedule task
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("apscheduler").setLevel(logging.WARNING)
        fmt = "%(asctime)s - %(levelname)s - %(name)s: %(message)s"
        if log_level == "DEBUG":
            logging.getLogger("httpx").setLevel(logging.INFO)
            fmt += " - {%(pathname)s - %(module)s - %(funcName)s - %(lineno)d}"

        # Set name and create the log file and folder if not exist
        log_folder = os.getenv("LOG_FOLDER", "log")
        log_file = f"{log_folder}/wouter-thuisserver-bot-{time.strftime('%d-%m-%Y')}.log"
        Path(log_folder).mkdir(parents=True, exist_ok=True)
        Path(log_file).touch(exist_ok=True)

        # Set logging level
        logging_level = getattr(logging, log_level, logging.INFO)

        # Setup the logging config
        logging.basicConfig(
            filename=log_file,
            level=logging_level,
            format=fmt,
            datefmt='%d-%m-%Y %H:%M:%S'
        )

        # Set console logging
        if args.verbose:
            console = logging.StreamHandler()
            console.setLevel(logging_level)
            console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
            logging.getLogger("wouter-thuisserver-bot").addHandler(console)

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
                except TelegramError as e:
                    logging.error(f"Telegram API error: {e}", exc_info=True)
                except Exception as e:
                    logging.error(f"Unexpected error while sending Telegram message: {e}", exc_info=True)


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
