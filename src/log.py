#!/usr/bin/python3

import os
import re
import logging
from telegram import Bot
from telegram.error import TelegramError


class Log:

    def __init__(self, args=False):

        # Init Telegram bot
        self.bot = Bot(os.getenv('BOT_TOKEN'))

        # Set logging format and config
        logging.root.handlers = []
        log_level = os.getenv('LOG_TYPE', 'INFO').upper()

        # set higher logging level for httpx to avoid all GET and POST requests being logged
        logging.getLogger("httpx").setLevel(logging.WARNING)
        fmt = "%(asctime)s:%(levelname)s:%(name)s - %(message)s"
        if log_level == "DEBUG":
            logging.getLogger("httpx").setLevel(logging.INFO)
            fmt += " - {%(pathname)s:%(module)s:%(funcName)s:%(lineno)d}"

        # Setup the logging config
        logging.basicConfig(
            filename='log/plex-download-bot.log',
            level=getattr(logging, log_level, logging.INFO),
            format=fmt,
            datefmt='%d-%m-%Y %H:%M:%S'
        )

        # Set console logging
        if args.verbose and getattr(args, 'verbose', False):
            console = logging.StreamHandler()
            console.setLevel(getattr(logging, log_level, logging.INFO))
            console.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(asctime)s - %(message)s'))
            logging.getLogger("").addHandler(console)

        # Set chat_id
        env_type = getattr(args, 'env', 'dev')
        self.own_chatid = os.getenv('CHAT_ID_GROUP') if env_type == "live" else os.getenv('CHAT_ID_WOUTER')


    async def logger(self, msg: str, silent=False, dtype="debug", telegram=True, chat_id=None) -> None:
        """ Send the log message to telegram and/or the log file """

        # Set chat_id
        if chat_id is None:
            chat_id = self.own_chatid

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
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=msg,
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
