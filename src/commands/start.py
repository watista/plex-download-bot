#!/usr/bin/python3

import json
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from src.commands.states import VERIFY, REQUEST_ACCOUNT, REQUEST_MOVIE, REQUEST_SERIE, VERIFY_PWD


class Start:

    def __init__(self, logger, functions):

        # Set default values
        self.log = logger
        self.function = functions


    async def start_msg(self, update: Update, context: CallbackContext) -> int:

        # Create the options keyboard
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎬 Film", callback_data="movie_request"),
                InlineKeyboardButton("📺 Serie", callback_data="serie_request")
            ],
            [
                InlineKeyboardButton("🆕 Nieuw account", callback_data="account_request")
            ],
            [
                InlineKeyboardButton("💁 Informatie", callback_data="info")
            ]
        ])

        # Send the message with the keyboard options
        await self.function.send_gif(f"*Plex Telegram Download Bot*\n\nWaar kan ik je vandaag mee helpen?", open("files/plex-gif.gif", "rb"), update, context, reply_markup)

        # Return to the next state
        return VERIFY

    async def verification(self, update: Update, context: CallbackContext) -> int:

        # Extract callback data and acknowledge the callback
        self.callback_data = update.callback_query.data
        await update.callback_query.answer()

        # Load JSON file
        with open("users.json", "r") as file:
            json_data = json.load(file)

        # Check if user is blocked
        if update.effective_chat.id in json_data["blocked_users"].values():
            await self.function.send_message(f"Je bent geblokkeerd om deze bot te gebruiken, als je denkt dat dit een fout is kan je contact opnemen met de serverbeheerder.", update, context)
            # Finish the conversation
            return ConversationHandler.END

        # Check if user_id is already known and verified
        if update.effective_chat.id in json_data["user_id"].values():
            # Return to the next state
            return await self.parse_request(update, context)
        else:
            # Ask for user password
            await self.function.send_message(f"Zo te zien is dit de eerste keer dat je gebruik maakt van deze bot. Om gebruik te maken van de download service heb je een wachtwoord nodig.\n\nVoer nu je wachtwoord in:", update, context)

            # Set amount on login tries
            self.login_tries = 0

            # Return to the next state
            return VERIFY_PWD


    async def verify_pwd(self, update: Update, context: CallbackContext) -> int:

        # Load JSON file
        with open("users.json", "r") as file:
            json_data = json.load(file)

        # Check if given password is known in json
        for key, value in json_data["users"].items():
            if value == update.message.text:
                await self.function.send_message(f"Je wachtwoord klopt!\n\nJe bent nu ingelogd als gebruiker: {key}", update, context)
                await asyncio.sleep(1)
                await self.function.send_message(f"Oke, terug naar waar we gebleven waren... 😁", update, context)
                await asyncio.sleep(1)

                # Write user_id to json
                json_data["user_id"][update.effective_chat["username"]] = update.effective_chat.id
                with open("users.json", "w") as file:
                    json.dump(json_data, file, indent=4)

                # Return to the next state
                return await self.parse_request(update, context)
            else:
                # Wrong password
                await self.function.send_message(f"Het opgegeven wachtwoord is onjuist, je hebt in totaal 3 pogingen, voordat je toegang wordt geblokkeerd.", update, context)

                # Bump wrong login tries
                self.login_tries += 1

                # add user to blocked_json
                if self.login_tries >= 3:
                    await self.function.send_message(f"Je hebt 3 keer het verkeeerde wachtwoord ingevoerd, je bent nu geblokkerd. Neem contact op met de serverbeheerder om deze blokkade op te heffen.", update, context)
                    json_data["blocked_users"][update.effective_chat["username"]] = update.effective_chat.id
                    with open("users.json", "w") as file:
                        json.dump(json_data, file, indent=4)
                    # Finish the conversation
                    return ConversationHandler.END

                # Return and retry the verify_pwd state
                await asyncio.sleep(1)
                await self.function.send_message(f"Voer nu je wachtwoord in:", update, context)
                return VERIFY_PWD


    async def parse_request(self, update, context) -> int:

        if self.callback_data == "serie_request":
            await self.function.send_message(f"Welke serie wil je graag op Plex zien?", update, context)
            return REQUEST_SERIE
        elif self.callback_data == "movie_request":
            await self.function.send_message(f"Welke film wil je graag op Plex zien?", update, context)
            return REQUEST_MOVIE
        elif self.callback_data == "account_request":
            await self.function.send_message(f"Het aanvragen van een account is op dit moment nog niet actief, probeer het later nog eens.", update, context)
            return ConversationHandler.END
            # return REQUEST_ACCOUNT
        else:
            # Send msg to user + logging
            await self.function.send_message(f"*😵 *Oeps, daar ging iets fout*\n\nDe serverbeheerder is op de hoogte gesteld van het probleem, je kan het nog een keer proberen in de hoop dat het dan wel werkt, of je kan het op een later moment nogmaals proberen.", update, context)
            await self.log.logger(f"Error happened during query data parsing", False, "error", True)
            return ConversationHandler.END
