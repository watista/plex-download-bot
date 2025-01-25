#!/usr/bin/python3

import os
# HIER UITEINDELIJK CHECKEN WAT WEG KAN
from src.commands.functions import Functions
from src.commands.help import Help
from src.commands.start import Start
from src.commands.serie import Serie
from src.commands.movie import Movie
from src.commands.account import Account

from telegram import Update, ForceReply
from telegram.ext import CommandHandler, filters, CallbackContext, CallbackQueryHandler, ApplicationBuilder, MessageHandler, Application


class Bot:

    def __init__(self, logger, plex, arr):

        # Set classes
        self.log = logger
        self.function = Functions(logger)
        self.help = Help(logger, self.function)
        self.serie = Serie(logger, self.function)
        self.movie = Movie(logger, self.function)
        self.account = Account(logger, self.function)
        self.start = Start(logger, self.function, self.serie, self.movie, self.account)

        # Create the Application using the new async API
        self.application = Application.builder().token(os.getenv('BOT_TOKEN')).concurrent_updates(False).read_timeout(300).build()

        # Add handlers
        self.application.add_handler(CallbackQueryHandler(      self.callback_handler))
        self.application.add_handler(CommandHandler("help",     self.help.help_command))
        self.application.add_handler(CommandHandler("start",    self.start.start_msg))
        self.application.add_handler(MessageHandler(None,       self.start.start_msg))

        # Add error handler
        self.application.add_error_handler(self.error_handler)

        # Start the bot
        self.application.run_polling(allowed_updates=Update.ALL_TYPES, poll_interval=1, timeout=5)


    # Function for unexpted errors
    async def error_handler(self, update: Update, context: CallbackContext) -> None:
        await self.log.logger(f"Error happened with Telegram dispatcher\nError: {context.error}", False, "error")


    async def callback_handler(self, update: Update, context: CallbackContext) -> None:

        # Answer query and remove keyboard
        query = update.callback_query
        await query.answer()
        # await query.edit_message_reply_markup(None)

        if query.data == "cancel":
            # Cancel request
            await self.function.send_message("Ok bye", update, context)

        elif query.data == "serie_request" or query.data == "movie_request" or query.data == "account_request":
            # From start.start_msg -> request serie/movie/account
            await self.start.verification(update, context, query.data)

        elif query.data == "info":
            # From start.start_msg -> request extra info
            await self.help.help_command(update, context)

        elif query.data[0:2] == "pwd":
            # From start.start_msg -> request extra info
            await self.help.help_command(update, context)

        else:
            # Should not happen
            await self.log.logger(f"❌ *Unknown callback data* ❌\nQuery data: *{query.data}*", False, "warning")
