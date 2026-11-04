#!/usr/bin/python3

from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler

from src.conversation import command_or_choice_line
from src.log import get_logger


log = get_logger(__name__)


class Maintenance:
    """Handlers used when the bot is running on the standby host.

    Plex, Sonarr, Radarr and Transmission are not reachable in this mode,
    so any user flow that needs them is answered with a maintenance notice
    instead of being processed.
    """

    MAINTENANCE_TEXT = (
        "🛠 *Onderhoud* 🛠\n\n"
        "De Plęx server is op dit moment niet bereikbaar, hierdoor is het aanvragen "
        "van films en series tijdelijk niet mogelijk.\n\n"
        "Probeer het later opnieuw zodra Plęx weer online is."
    )

    def __init__(self, logger, functions):
        self.log = logger
        self.function = functions

    async def media_maintenance(self, update: Update, context: CallbackContext) -> int:
        """/aanmelden_serie and /afmelden_serie: the maintenance message, with
        that outcome in the line of the command."""
        log.info(**command_or_choice_line(update, maintenance=True))
        return await self.notice(update, context)

    async def notice(self, update: Update, context: CallbackContext) -> int:
        """Reply with the maintenance message and end the conversation.

        Used for film/serie/serie-update flows that depend on the primary host.
        """
        if update.callback_query:
            await update.callback_query.answer()

        await self.function.send_message(self.MAINTENANCE_TEXT, update, context)
        return ConversationHandler.END
