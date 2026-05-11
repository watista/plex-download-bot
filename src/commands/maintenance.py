#!/usr/bin/python3

from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler


class Maintenance:
    """Handlers used when the bot is running on the standby host.

    Plex, Sonarr, Radarr and Transmission are not reachable in this mode,
    so any user flow that needs them is answered with a maintenance notice
    instead of being processed.
    """

    MAINTENANCE_TEXT = (
        "🛠 *Onderhoud*\n\n"
        "De server is op dit moment niet bereikbaar, waardoor het aanvragen "
        "van films en series tijdelijk niet mogelijk is.\n\n"
        "Algemene informatie en het aanvragen van een nieuw account werkt wel. "
        "Probeer het later opnieuw zodra Plęx weer online is."
    )

    def __init__(self, logger, functions):
        self.log = logger
        self.function = functions

    async def media_maintenance(self, update: Update, context: CallbackContext) -> int:
        """Reply with the maintenance message and end the conversation.

        Used for film/serie/serie-update flows that depend on the primary host.
        """
        if update.callback_query:
            await update.callback_query.answer()

        await self.log.logger(
            f"Maintenance reply sent - Username: {update.effective_user.first_name} - User ID: {update.effective_user.id}",
            False,
            "info",
            False,
        )

        await self.function.send_message(self.MAINTENANCE_TEXT, update, context)
        return ConversationHandler.END
