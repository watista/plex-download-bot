#!/usr/bin/python3

import os
import traceback

from src.states import VERIFY, REQUEST_ACCOUNT, REQUEST_ACCOUNT_EMAIL, REQUEST_ACCOUNT_PHONE, REQUEST_ACCOUNT_REFER, REQUEST_MOVIE, REQUEST_SERIE, VERIFY_PWD, MOVIE_OPTION, MOVIE_NOTIFY, SERIE_OPTION, SERIE_NOTIFY, MOVIE_UPGRADE, SERIE_UPGRADE, SERIE_UPGRADE_OPTION, MOVIE_UPGRADE_INFO, SERIE_UPGRADE_INFO, HELP_CHOICE, HELP_OTHER
from src.functions import Functions
from src.commands.help import Help
from src.commands.start import Start
from src.commands.serie import Serie
from src.commands.movie import Movie
from src.commands.account import Account
from src.commands.schedule import Schedule

from telegram import Update, BotCommand
from telegram.ext import (
    CommandHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler,
    MessageHandler,
    Application,
    ConversationHandler
)


class Bot:

    def __init__(self, args, logger):

        # Set classes
        self.args = args
        self.log = logger
        self.function = Functions(logger)
        self.help = Help(logger, self.function)
        self.start = Start(args, logger, self.function)
        self.serie = Serie(args, logger, self.function)
        self.movie = Movie(args, logger, self.function)
        self.account = Account(logger, self.function)
        self.schedule = Schedule(args, logger, self.function)

        # Create the Application using the new async API
        self.application = Application.builder().token(os.getenv('BOT_TOKEN')).concurrent_updates(False).read_timeout(300).build(
        ) if args.env == "live" else Application.builder().token(os.getenv('BOT_TOKEN_DEV')).concurrent_updates(False).read_timeout(300).build()

        # Add conversation handler with different states
        self.application.add_handler(ConversationHandler(
            # entry_points=[CommandHandler("start", self.start.start_msg)],
            entry_points=[CommandHandler("start", self.start.start_msg),
                          CommandHandler("help", self.help.help_command),
                          MessageHandler(filters.TEXT & ~filters.COMMAND, self.start.start_msg)],
            states={
                VERIFY: [
                    CallbackQueryHandler(
                        self.start.verification, pattern="^(movie_request|serie_request)$"),
                    CallbackQueryHandler(
                        self.start.parse_request, pattern="^account_request$"),
                    CallbackQueryHandler(
                        self.help.help_command_button, pattern="^info$")
                ],
                VERIFY_PWD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.start.verify_pwd)],
                REQUEST_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.account.request_account)],
                REQUEST_ACCOUNT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.account.request_account_email)],
                REQUEST_ACCOUNT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.account.request_account_phone)],
                REQUEST_ACCOUNT_REFER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.account.request_account_refer)],
                REQUEST_MOVIE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.movie.request_media)],
                REQUEST_SERIE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.serie.request_media)],
                MOVIE_OPTION: [CallbackQueryHandler(self.movie.media_option, pattern="^(0|1|2|3|4)$")],
                SERIE_OPTION: [CallbackQueryHandler(self.serie.media_option, pattern="^(0|1|2|3|4)$")],
                MOVIE_NOTIFY: [CallbackQueryHandler(self.movie.stay_notified, pattern="^(film_notify_yes|film_notify_no)$")],
                SERIE_NOTIFY: [CallbackQueryHandler(self.serie.stay_notified, pattern="^(serie_notify_yes|serie_notify_no)$")],
                MOVIE_UPGRADE: [CallbackQueryHandler(self.movie.media_upgrade, pattern="^(film_upgrade_yes|film_upgrade_no)$")],
                SERIE_UPGRADE: [CallbackQueryHandler(self.serie.media_upgrade, pattern="^(serie_upgrade_yes|serie_upgrade_no)$")],
                MOVIE_UPGRADE_INFO: [CallbackQueryHandler(self.movie.media_upgrade_info, pattern="^(quality|subs|ads|other)$")],
                SERIE_UPGRADE_INFO: [CallbackQueryHandler(self.serie.media_upgrade_info, pattern="^(quality|subs|ads|other)$")],
                SERIE_UPGRADE_OPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.serie.media_upgrade_option)],
                HELP_CHOICE: [
                    CallbackQueryHandler(
                        self.help.usage, pattern="^help_use$"),
                    CallbackQueryHandler(
                        self.help.faq, pattern="^help_faq$"),
                    CallbackQueryHandler(
                        self.help.new_account, pattern="^help_new_account$"),
                    CallbackQueryHandler(
                        self.help.quality, pattern="^help_quality$"),
                    CallbackQueryHandler(
                        self.help.other, pattern="^help_other$")
                ],
                HELP_OTHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.help.other_reply)]
            },
            fallbacks=[CommandHandler("stop", self.stop)],
            conversation_timeout=86400
        )
        )

        # Add stand-alone handlers
        self.application.add_handler(
            CommandHandler("help", self.help.help_command))

        # Add error handler
        self.application.add_error_handler(self.error_handler)

        # Run the publish command function
        self.application.job_queue.run_once(lambda _: self.application.create_task(self.publish_command_list()), when=0)

        # Enable the Schedule Job Queue
        self.application.job_queue.run_repeating(
            self.schedule.check_notify_list, interval=7200, first=0)
        self.application.job_queue.run_repeating(
            self.schedule.check_timestamp, interval=604800, first=0)

        # Start the bot
        self.application.run_polling(
            allowed_updates=Update.ALL_TYPES, poll_interval=1, timeout=5)

    async def publish_command_list(self):
        """ Create and publish command list """
        command_list = [
            BotCommand("start", "Commando om de bot te starten"),
            BotCommand("help", "Krijg alle informatie te zien van deze bot")
        ]
        await self.application.bot.set_my_commands(command_list)

    async def error_handler(self, update: Update, context: CallbackContext) -> None:
        """ Function for unexpted errors """
        error_message = "".join(traceback.format_exception(
            None, context.error, context.error.__traceback__))
        await self.log.logger(f"Error happened with Telegram dispatcher\n{error_message}", False, "error")

    async def stop(self, update: Update, context: CallbackContext) -> None:
        """ Cancel command """
        await self.function.send_message(f"Oke gestopt. Stuur /start om opnieuw te beginnen.", update, context)
        return ConversationHandler.END
