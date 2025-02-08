#!/usr/bin/python3

import asyncio
from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler


class Help:

    def __init__(self, logger, functions):

        # Set default values
        self.log = logger
        self.function = functions


    async def help_command_button(self, update: Update, context: CallbackContext) -> None:

        # Extract callback data and acknowledge the callback
        callback_data = update.callback_query.data
        await update.callback_query.answer()

        # run help info function
        await self.help_command(update, context)

        return ConversationHandler.END


    async def help_command(self, update: Update, context: CallbackContext) -> None:

        # Senf help info
        await self.function.send_message("*🔥Welkom bij de Plex Telegram Download bot🔥*\n\nDeze bot kan voor 3 zaken gebruikt worden:", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("*#1 Een film aanvragen*\n\nHeel simpel, start de bot door /start te sturen, kies daarna voor '🎬 Film' en geef aan welke film je mist. Hierna krijg je een aantal opties die gedownload kunnen worden. Maak je keuze en voor je het weet staat de film online.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("*#2 Een serie aanvragen*\n\nOok weer heel simpel, en precies hetzelfde als een film aanvragen. Begin de bot door /start te sturen, kies voor '📺 Serie' en volg de stappen.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("*#3 Een account aanvragen*\n\nHeb je nog geen account en wil je deze wel graag? Begin de bot dan door /start te sturen en kies voor de optie '🆕 Nieuw account'. Er worden een paar vragen gestuurd, hierna wordt er contact met je opgenomen over de account aanvraag.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("Je kan altijd tijdens het gebruik van deze bot stoppen door /stop te sturen. Wil je de bot weer beginnen? Stuur dan /start", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("Heb je nog andere vragen? Stuur dan een bericht naar de serverbeheerder via Telegram of Whatsapp.", update, context)
        await self.log.logger(f"*ℹ️ User invoked the /help command ℹ️*\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")
