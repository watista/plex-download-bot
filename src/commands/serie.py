#!/usr/bin/python3

import asyncio

from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler


class Serie:

    def __init__(self, logger, functions, sonarr):

        # Set default values
        self.log = logger
        self.function = functions
        self.sonarr = sonarr


    async def request_serie(self, update: Update, context: CallbackContext) -> None:
        print("test")
        return ConversationHandler.END
