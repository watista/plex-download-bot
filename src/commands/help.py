#!/usr/bin/python3

from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler


class Help:

    def __init__(self, logger, functions):

        # Set default values
        self.log = logger
        self.function = functions


    async def help_command_button(self, update: Update, context: CallbackContext) -> int:

        # Extract callback data and acknowledge the callback
        callback_data = update.callback_query.data
        await update.callback_query.answer()

        # run help info function
        await self.help_command(update, context)

        return ConversationHandler.END


    async def help_command(self, update: Update, context: CallbackContext) -> None:

        # Senf hepl info
        text = [
        "<pre>Command              Gebruik                        Uitleg                              \n",
        "---------------------------------------------------------------------------------------------\n",
        "/help                /help                          Toont dit uitleg bericht                 \n",
        "/iets                /iets 000001246                Dit doet iets                      </pre>\n"
        ]
        await self.function.send_message("".join(text), update, context, None, 'HTML')
