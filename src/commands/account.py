#!/usr/bin/python3

import asyncio

from telegram import Update
from telegram.ext import CallbackContext


class Account:

    def __init__(self, logger, functions):

        # Set default values
        self.log = logger
        self.function = functions


    async def request_account(self, update, context) -> None:
        return ConversationHandler.END
