#!/usr/bin/python3

import asyncio
from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler

from src.states import REQUEST_ACCOUNT_EMAIL, REQUEST_ACCOUNT_PHONE, REQUEST_ACCOUNT_REFER


class Account:

    def __init__(self, logger, functions):

        # Set default values
        self.log = logger
        self.function = functions


    async def request_account(self, update: Update, context: CallbackContext) -> int:
        """ Handles the first_name question for the account request """

        # Create a dict to store the information
        self.info_dict = {"first_name": update.message.text}

        # Send messages
        await self.function.send_message(f"Leuk je te ontmoeten {update.message.text} 😀", update, context)
        await asyncio.sleep(1)
        await self.function.send_message(f"Om toegang te krijgen tot Plex, heb je een Plex account nodig die ik aan mijn server kan toevoegen. Een Plex account kan je aanmaken via <a href='https://plex.tv'>plex.tv</a>.", update, context, None, "HTML")
        await asyncio.sleep(1)
        await self.function.send_message(f"Wat is het e-mailadres van je Plex account?", update, context)

        # Return to next state
        return REQUEST_ACCOUNT_EMAIL


    async def request_account_email(self, update: Update, context: CallbackContext) -> int:
        """ Handles the email question for the account request """

        # Add info to dict
        self.info_dict["email"] = update.message.text

        # Send messages
        await self.function.send_message(f"Oke staat genoteerd.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message(f"Ook niet geheel onbelangrijk, wat is je telefoonnummer? Deze heb ik nodig om je een Tikkie te sturen (hierover later meer).", update, context)

        # Return to next state
        return REQUEST_ACCOUNT_PHONE


    async def request_account_phone(self, update: Update, context: CallbackContext) -> int:
        """ Handles the email question for the account request """

        # Add info to dict
        self.info_dict["phone"] = update.message.text

        # Send messages
        await self.function.send_message(f"Check ✅", update, context)
        await asyncio.sleep(1)
        await self.function.send_message(f"Dan als laatste vraag, puur uit nieuwschierigheid, van wie heb je gehoord over Plex?", update, context)

        # Return to next state
        return REQUEST_ACCOUNT_REFER


    async def request_account_refer(self, update: Update, context: CallbackContext) -> None:
        """ Handles the email question for the account request """

        # Add info to dict
        self.info_dict["referrer"] = update.message.text

        # Send messages
        await self.function.send_message(f"Got it!", update, context)
        await asyncio.sleep(1)
        await self.function.send_message(f"Dat waren al mijn vragen, dan dan een paar huis, tuin en keuken mededelingen:", update, context)
        await asyncio.sleep(1)
        await self.function.send_message(f"Ik ga je toevoegen aan de Plex server, je kan dan Plex via de mobiele app bekijken of via <a href='https://server.wouterpaas.nl/'>server.wouterpaas.nl</a> in de browser. Als je direct vanaf de App wilt kijken moet je een Plex Pass kopen, streamen vanaf de App is gratis.", update, context, None, "HTML")
        await asyncio.sleep(1)
        await self.function.send_message(f"De eerste maand is gratis en kan je het even uitproberen, daarna worden de kosten 15 euro per jaar om de stroomkosten te compenseren van de server. Hiervoor stuur ik een Tikkie naar je telefoonnummer.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message(f"Je ontvangt dan ook een wachtwoord om series en films aan te vragen via deze bot. Hiermee kan je series of films die je mist aanvragen, deze worden dan automatisch gedownload.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message(f"Heb je vragen over het gebruik van Plex (en dan vooral de App)? Lees dan even de <a href='https://docs.wouterpaas.nl/'>documentatie</a> door die ik heb opgesteld.", update, context, None, "HTML")
        await asyncio.sleep(1)
        await self.function.send_message(f"Dat was alles, zoals gezegd zal ik je toevoegen aan de server en je hierover een seintje geven op je telefoonnummer, als je nog vragen hebt kan je die dan via Whatsapp aan me stellen.", update, context)
        await asyncio.sleep(1)
        await self.function.send_message(f"Veel kijkplezier alvast! 😎", update, context)

        # Send the request info
        await self.log.logger(f"*🎉 New account requested 🎉*\n\nName: {self.info_dict['first_name']}\nEmail: {self.info_dict['email']}\nPhone: {self.info_dict['phone']}\nVia: {self.info_dict['referrer']}", False, "info")

        # End the conversation
        return ConversationHandler.END
