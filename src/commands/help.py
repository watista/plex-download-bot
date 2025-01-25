#!/usr/bin/python3

from telegram import Update
from telegram.ext import CallbackContext


class Help:

    def __init__(self, logger, functions):

        # Set default values
        self.log = logger
        self.function = functions


    async def help_command(self, update: Update, context: CallbackContext) -> None:

        text = [
        "<pre>Command              Gebruik                        Uitleg                              \n",
        "---------------------------------------------------------------------------------------------\n",
        "/help                /help                          Toont dit uitleg bericht                 \n",
        "/iets                /iets 000001246                Dit doet iets                      </pre>\n"
        ]
        await self.function.send_message("".join(text), update, context, None, 'HTML')
