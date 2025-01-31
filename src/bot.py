#!/usr/bin/python3

import os
# HIER UITEINDELIJK CHECKEN WAT WEG KAN
from src.commands.states import VERIFY, REQUEST_ACCOUNT, REQUEST_MOVIE, REQUEST_SERIE, VERIFY_PWD, MOVIE_OPTION
from src.commands.functions import Functions
from src.commands.help import Help
from src.commands.start import Start
from src.commands.serie import Serie
from src.commands.movie import Movie
from src.commands.account import Account

from telegram import Update, ForceReply
from telegram.ext import (
    CommandHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler,
    ApplicationBuilder,
    MessageHandler,
    Application,
    ConversationHandler
)

class Bot:

    def __init__(self, args, logger, plex, radarr, sonarr):

        # Set classes
        self.args = args
        self.log = logger
        self.function = Functions(logger)
        self.help = Help(logger, self.function)
        self.serie = Serie(args, logger, self.function, sonarr)
        self.movie = Movie(args, logger, self.function, radarr)
        self.account = Account(logger, self.function)
        self.start = Start(logger, self.function)


        # Create the Application using the new async API
        self.application = Application.builder().token(os.getenv('BOT_TOKEN')).concurrent_updates(False).read_timeout(300).build()

        # Add conversation handler with different states
        self.application.add_handler(ConversationHandler(
            entry_points=[CommandHandler("start", self.start.start_msg)], # Hier later miss nog alle mogelijke berichten als start gebruiken
            states={
                # HIER OVERAL NOG EXTRA COMMAND HANDLER INBOUWEN MET /CANCEL OM OP ELK MOMENT TE STOPPPEN
                VERIFY: [
                    CallbackQueryHandler(self.start.verification, pattern="^(movie_request|serie_request|account_request)$"),
                    CallbackQueryHandler(self.help.help_command_button, pattern='^info$')
                ],
                VERIFY_PWD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.start.verify_pwd)],
                REQUEST_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.account.request_account)],
                REQUEST_MOVIE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.movie.request_movie)],
                REQUEST_SERIE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.serie.request_serie)],
                MOVIE_OPTION: [
                    CallbackQueryHandler(self.movie.movie_option, pattern="0"),
                    CallbackQueryHandler(self.movie.movie_option, pattern="1"),
                    CallbackQueryHandler(self.movie.movie_option, pattern="2"),
                    CallbackQueryHandler(self.movie.movie_option, pattern="3"),
                    CallbackQueryHandler(self.movie.movie_option, pattern="4")
                ]
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
            )
        )

        # Add stand-alone handlers
        self.application.add_handler(CommandHandler("help", self.help.help_command))

        # Add error handler
        self.application.add_error_handler(self.error_handler)

        # Start the bot
        self.application.run_polling(allowed_updates=Update.ALL_TYPES, poll_interval=1, timeout=5)


    # Function for unexpted errors
    async def error_handler(self, update: Update, context: CallbackContext) -> None:
        await self.log.logger(f"Error happened with Telegram dispatcher\nError: {context.error}", False, "error")


    # Cancel command
    async def cancel(self, update: Update, context: CallbackContext) -> int:
        await self.function.send_message(f"Oke gestopt. Stuur /start om opnieuw te beginnen.", update, context)
        return ConversationHandler.END
