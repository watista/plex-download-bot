#!/usr/bin/python3

import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from src.states import HELP_CHOICE, HELP_OTHER


class Help:

    def __init__(self, logger, functions):

        # Set default values
        self.log = logger
        self.function = functions

    async def help_command_button(self, update: Update, context: CallbackContext) -> None:

        # Extract callback data and acknowledge the callback
        await update.callback_query.answer()

        # Create the options keyboard
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🤖 Hoe gebruik je deze bot?", callback_data="help_use")
            ],
            [
                InlineKeyboardButton("❓ Veelgestelde vragen", callback_data="help_faq")
            ],
            [
                InlineKeyboardButton("🆕 Nieuw account aanvragen", callback_data="help_new_account")
            ],
            [
                InlineKeyboardButton("📺 Kwaliteit van een serie of film", callback_data="help_quality")
            ],
            [
                InlineKeyboardButton("📍 Anders", callback_data="help_other")
            ]
        ])

        # Send the message with the keyboard options
        await self.function.send_message(f"Over welk onderwerp wil je graag meer informatie?", update, context, reply_markup)

        # Return to the next state
        return HELP_CHOICE


    async def help_command(self, update: Update, context: CallbackContext) -> int:

        # Create the options keyboard
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🤖 Hoe gebruik je deze bot?", callback_data="help_use")
            ],
            [
                InlineKeyboardButton("❓ Veelgestelde vragen", callback_data="help_faq")
            ],
            [
                InlineKeyboardButton("🆕 Nieuw account aanvragen", callback_data="help_new_account")
            ],
            [
                InlineKeyboardButton("📺 Kwaliteit van een serie of film", callback_data="help_quality")
            ],
            [
                InlineKeyboardButton("📍 Anders", callback_data="help_other")
            ]
        ])

        # Send the message with the keyboard options
        await self.function.send_message(f"Over welk onderwerp wil je graag meer informatie?", update, context, reply_markup)

        # Return to the next state
        return HELP_CHOICE


    async def usage(self, update: Update, context: CallbackContext) -> None:

        # Extract callback data and acknowledge the callback
        await update.callback_query.answer()

        # Log
        await self.log.logger(f"*ℹ️ User invoked the /help - Hoe gebruik je deze bot command ℹ️*\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")

        # Send messages
        await self.function.send_message("Deze bot kan je voor 3 dingen gebruiken:\n\n 1. Een account aanvragen voor de Plex server\n 2. Nieuwe films aanvragen\n 3. Nieuwe series aanvragen", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("*1. Een nieuw account aanvragen*\n\nBen je zo enthousiast over Plex en denk je dat een vriend, broertje, moeder of opa ook wel een Plex account wilt? Vraag dan een nieuw account aan via deze bot.\n\nAls je /start stuurt krijg je 4 opties, één daarvan is de optie *🆕 Nieuw account*. Als je deze optie kiest worden er een aantal vragen gesteld zoals je naam, email adres, telefoon, etc. die ik nodig heb om iemand toe te voegen aan de server. Zodra ik de gegevens heb ontvangen stuur ik de aanvrager een Whatsapp bericht met alle laatste informatie en dan kan het kijkplezier beginnen 😎", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("*2. Nieuwe film(s) aanvragen*\n\nMis je een film op Plex? Geen probleem, deze kan je makkelijk aanvragen via deze bot waarna de film automatisch gedownload wordt, vaak is dit al binnen een uur!\n\nOok in dit geval begin je door /start te sturen, kies hierna de optie *🎬 Film*. Je wordt gevraagd om de naam van de film te sturen, de bot geeft je daarna een maximum van 5 opties op basis van de film titel die je hebt gestuurd. Kies de film die je graag wilt en that's it. Je krijgt ook nog de optie om op de hoogte gehouden te worden voor als de film online staat. Super simpel dus 😄", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("*3. Nieuwe serie(s) aanvragen*\n\nPrecies hetzelfde als bij het aanvragen van een film, alleen in dit geval klik je op de knop *📺 Serie*.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("Gaat er tijdens het proces iets fout of wil je graag opnieuw beginnen? Dan kan je altijd op elk moment /stop sturen, de bot stopt dan en kan opnieuw gestart worden door /start te sturen.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("Heb je verder nog vragen, stuur dan /help om dit help menu opnieuw te zien of stuur de serverbeheerder een bericht op Whatsapp.", update, context)

        # End convo
        return ConversationHandler.END


    async def faq(self, update: Update, context: CallbackContext) -> None:

        # Extract callback data and acknowledge the callback
        await update.callback_query.answer()

        # Log
        await self.log.logger(f"*ℹ️ User invoked the /help - FAQ command ℹ️*\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")

        # Send messages
        await self.function.send_message("Heb je net een nieuw account en kom je ergens niet uit? Hier wat extra info over de meest voorkomende vragen:", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("*Hoeveel kost Plex?*\n\nPlex is de eerste maand gratis om uit te proberen, daarna kost het 15 euro per jaar om de stroomkosten van de server te compenseren.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("*Kan ik vanaf mijn mobiel Plex kijken?*\n\nAls je de Plex app gebruikt kan je niet direct op je mobiel kijken, hiervoor moet je (eenmalig) de Plex app kopen. Streamen naar een TV vanaf de Plex app is wel gratis. Als je toch Plex wilt kijken op je mobiel en je wilt niet betalen kan vanaf je browser op je mobiel kijken, ga hiervoor naar https://server.wouterpaas.nl/", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("*Kan ik meteen series en films aanvragen?*\n\nJa! Zodra je een wachtwoord hebt ontvangen via Whatsapp kan deze bot gebruiken om films en series aan te vragen.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("*Hoe stel ik de Plex app het beste in?*\n\nHet instellen van de Plex app kan soms wat ingewikkeld zijn, lees de uitgebreide documentatie hiervoor op https://docs.wouterpaas.nl/", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("*Ik zie alleen maar hele oude films en series*\n\nPlex biedt zelf ook content aan wat vaak hele oude en slechte films en series zijn. Om deze content niet te zien in de app kan je het beste de documentatie lezen over hoe je de app instelt.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("*Mag ik mijn Plex account delen?*\n\nJe mag je account delen met mensen uit hetzelfde huishouden, ken je andere mensen die ook willen kijken? Vraag dan een nieuw account aan voor deze personen zodat de stroomkosten gecompenseerd kunnen worden.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("*Ik zie geen Nederlandse ondertiteling*\n\nOndertiteling, en dan specifiek Nederlandse, is soms niet aanwezig. Je kan in de Plex app handmatig zoeken naar ondertiteling in andere talen maar het is geen garantie dat deze er altijd is, vooral bij net nieuwe films of serie afleveringen kan er soms geen ondertiteling zijn. Wil je weten hoe je handmatig ondertiteling zoekt? Bekijk dan de documentatie via https://docs.wouterpaas.nl/", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("Heb je verder nog vragen, stuur dan /help om dit help menu opnieuw te zien of stuur de serverbeheerder een bericht op Whatsapp.", update, context)

        # End convo
        return ConversationHandler.END


    async def new_account(self, update: Update, context: CallbackContext) -> None:

        # Extract callback data and acknowledge the callback
        await update.callback_query.answer()

        # Log
        await self.log.logger(f"*ℹ️ User invoked the /help - New account command ℹ️*\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")

        # Send messages
        await self.function.send_message("*Een nieuw account aanvragen*\n\nBen je zo enthousiast over Plex en denk je dat een vriend, broertje, moeder of opa ook wel een Plex account wilt? Vraag dan een nieuw account aan via deze bot.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("Als je /start stuurt krijg je 4 opties, één daarvan is de optie *🆕 Nieuw account*. Als je deze optie kiest worden er een aantal vragen gesteld zoals je naam, email adres, telefoon, etc. die ik nodig heb om iemand toe te voegen aan de server. Zodra ik de gegevens heb ontvangen stuur ik de aanvrager een Whatsapp bericht met alle laatste informatie en dan kan het kijkplezier beginnen 😎", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("Heb je verder nog vragen, stuur dan /help om dit help menu opnieuw te zien of stuur de serverbeheerder een bericht op Whatsapp.", update, context)

        # End convo
        return ConversationHandler.END


    async def quality(self, update: Update, context: CallbackContext) -> None:

        # Extract callback data and acknowledge the callback
        await update.callback_query.answer()

        # Log
        await self.log.logger(f"*ℹ️ User invoked the /help - Quality command ℹ️*\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")

        # Send messages
        await self.function.send_message("Staat er een film of serie op Plex en is de kwaliteit ronduit slecht, staat er reclame in het scherm of zitten er ingebakken chinese ondertitels in? Dan kan je de film of serie opnieuw aanvragen. Je krijgt na het kiezen van de film/serie de vraag of er iets mis is met de kwaliteit. Geef hierbij aan wat er mis is en ik zal de film/serie opnieuw downloaden met goede kwaliteit.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message("Heb je verder nog vragen, stuur dan /help om dit help menu opnieuw te zien of stuur de serverbeheerder een bericht op Whatsapp.", update, context)

        # End convo
        return ConversationHandler.END


    async def other(self, update: Update, context: CallbackContext) -> int:

        # Extract callback data and acknowledge the callback
        await update.callback_query.answer()

        # Log
        await self.log.logger(f"*ℹ️ User invoked the /help - Other command ℹ️*\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")

        # Send messages
        await self.function.send_message("Heb je nog een vraag, op- of aanmerking die niet beantwoord is? Stuur mij dan een bericht via Whatsapp of typ en stuur je bericht nu in Telegram en ik zal je zo snel mogelijk een reactie geven. Stuur ook meteen even je telefoonnummer mee voor de handigheid. Wil je geen bericht sturen? Klik dan op, of stuur /stop", update, context)

        # Next state
        return HELP_OTHER


    async def other_reply(self, update: Update, context: CallbackContext) -> None:

        # Send messages
        await self.function.send_message("Bedankt voor je bericht, ik neem zo snel mogelijk contact met je op!", update, context)
        await self.log.logger(f"*ℹ️ User send a question ℹ️*\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}\n\n{update.message.text}", False, "info")

        # End convo
        return ConversationHandler.END
