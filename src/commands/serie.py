#!/usr/bin/python3

from telegram import Update
from telegram.ext import CallbackContext


class Serie:

    def __init__(self, logger, functions):

        # Set default values
        self.log = logger
        self.function = functions


    async def request_serie(self, update: Update, context: CallbackContext) -> None:
        print(" test")
