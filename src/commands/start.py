#!/usr/bin/python3

import json
import asyncio
import aiofiles
from datetime import datetime
from typing import Union, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from src.states import VERIFY, REQUEST_ACCOUNT, REQUEST_MOVIE, REQUEST_SERIE, VERIFY_PWD


class Start:

    def __init__(self, args, logger, functions):

        # Set default values
        self.log = logger
        self.function = functions

        # Set data.json/stats.json file based on live/dev arg
        self.data_json = "data.json" if args.env == "live" else "data.dev.json"
        self.stats_json = "stats.json" if args.env == "live" else "stats.dev.json"

    async def start_msg(self, update: Update, context: CallbackContext) -> int:

        # Debug usage log
        await self.log.logger(f"User started bot with /start - Username: {update.effective_user.first_name} - User ID: {update.effective_user.id}", False, "info", False)

        # Create the options keyboard
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎬 Film", callback_data="movie_request"),
                InlineKeyboardButton("📺 Serie", callback_data="serie_request")
            ],
            [
                InlineKeyboardButton(
                    "🆕 Nieuw account", callback_data="account_request")
            ],
            [
                InlineKeyboardButton("💁 Informatie", callback_data="info")
            ]
        ])

        # Send the message with the keyboard options
        await self.function.send_gif(f"*🔥🤖 Wouter Thuis-Server Bot 🤖🔥*\n\nWaar kan ik je vandaag mee helpen?\n\n_Stuur /stop op elk moment om de bot te stoppen_", open("files/watch-serie.gif", "rb"), update, context, reply_markup)

        # Return to the next state
        return VERIFY

    async def verification(self, update: Update, context: CallbackContext) -> Optional[int]:

        # Extract callback data and acknowledge the callback
        context.user_data["callback_data"] = update.callback_query.data
        await update.callback_query.answer()

        # Load JSON file
        async with aiofiles.open(self.data_json, "r") as file:
            json_data = json.loads(await file.read())

        # Check if user is blocked
        if str(update.effective_user.id) in json_data["blocked_users"]:
            await self.function.send_message(f"Je bent geblokkeerd om deze bot te gebruiken, als je denkt dat dit een fout is kan je contact opnemen met de serverbeheerder.", update, context)
            await self.log.logger(f"*ℹ️ A blocked user tried to login ℹ️*\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")
            # Finish the conversation
            return ConversationHandler.END

        # Check if user_id is already known and verified
        if str(update.effective_user.id) in json_data["user_id"]:

            async with aiofiles.open(self.stats_json, "r+") as file:
                data = json.loads(await file.read())
                data.setdefault(str(update.effective_user.id), {
                                "logins": {}, "film_requests": {}, "serie_requests": {}})
                data[str(update.effective_user.id)]["logins"][datetime.now().strftime(
                    "%d-%m-%Y %H:%M:%S")] = update.effective_user.first_name
                await file.seek(0)
                await file.write(json.dumps(data, indent=4))
                await file.truncate()

            # Return to the next state
            return await self.parse_request(update, context)

        # Ask for user password
        await self.function.send_message(f"Zo te zien is dit de eerste keer dat je gebruik maakt van deze bot. Om gebruik te maken van de bot heb je een wachtwoord nodig.\n\nVoer nu je wachtwoord in:", update, context)

        # Set amount on login tries
        context.user_data["login_tries"] = 0

        # Return to the next state
        return VERIFY_PWD

    async def verify_pwd(self, update: Update, context: CallbackContext) -> Optional[int]:

        # Load JSON file
        async with aiofiles.open(self.data_json, "r") as file:
            json_data = json.loads(await file.read())

        # Check if given password is known in json
        for key, value in json_data["users"].items():
            if value == update.message.text:
                await self.log.logger(f"*ℹ️ First time login for user ℹ️*\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")
                await self.function.send_message(f"Je wachtwoord klopt!\n\nJe bent nu ingelogd als gebruiker: {key}", update, context)
                await asyncio.sleep(1)

                # Write user_id to json
                json_data["user_id"][str(
                    update.effective_user.id)] = update.effective_user.first_name
                async with aiofiles.open(self.data_json, "w") as file:
                    await file.write(json.dumps(json_data, indent=4))

                # Create user in stats.json
                async with aiofiles.open(self.stats_json, "r+") as file:
                    data = json.loads(await file.read())
                    data[str(update.effective_user.id)] = {
                        "logins": {datetime.now().strftime("%d-%m-%Y %H:%M:%S"): update.effective_user.first_name},
                        "film_requests": {},
                        "serie_requests": {}
                    }
                    await file.seek(0)
                    await file.write(json.dumps(data, indent=4))
                    await file.truncate()

                # Return to the next state
                return await self.parse_request(update, context)

        # Bump wrong login tries
        context.user_data["login_tries"] += 1

        # add user to blocked_json
        if context.user_data["login_tries"] >= 3:
            # Send message and add to blocklist
            await self.log.logger(f"*ℹ️ User has been blocked ℹ️*\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")
            await self.function.send_message(f"Je hebt 3 keer het verkeeerde wachtwoord ingevoerd, je bent nu geblokkerd. Neem contact op met de serverbeheerder om deze blokkade op te heffen.", update, context)
            json_data["blocked_users"][str(
                update.effective_user.id)] = update.effective_user.first_name
            async with aiofiles.open(self.data_json, "w") as file:
                await file.write(json.dumps(json_data, indent=4))
            # Finish the conversation
            return ConversationHandler.END

        # Wrong password
        await self.function.send_message(f"Het opgegeven wachtwoord is onjuist, je hebt nog {3 - context.user_data['login_tries']} pogingen voordat je toegang wordt geblokkeerd.", update, context)

        # Return and retry the verify_pwd state
        await asyncio.sleep(1)
        await self.function.send_message(f"Voer nu je wachtwoord in:", update, context)
        return VERIFY_PWD

    async def parse_request(self, update: Update, context: CallbackContext) -> Optional[int]:

        if not context.user_data.get("callback_data"):
            await update.callback_query.answer()
            await self.function.send_message(f"Leuk dat je interesse hebt in Plęx. Voordat ik een account voor je kan aanmaken heb ik eerst wat informatie van je nodig.", update, context)
            await asyncio.sleep(1)
            await self.function.send_message(f"Om te beginnen, hoe mag ik je noemen?", update, context)
            return REQUEST_ACCOUNT
        elif context.user_data["callback_data"] == "serie_request":
            await self.function.send_message(f"Welke serie wil je graag op Plęx zien?", update, context)
            return REQUEST_SERIE
        elif context.user_data["callback_data"] == "movie_request":
            await self.function.send_message(f"Welke film wil je graag op Plęx zien?", update, context)
            return REQUEST_MOVIE
        else:
            # Send msg to user + logging
            await self.function.send_message(f"*😵 *Oeps, daar ging iets fout*\n\nDe serverbeheerder is op de hoogte gesteld van het probleem, je kan het nog een keer proberen in de hoop dat het dan wel werkt, of je kan het op een later moment nogmaals proberen.", update, context)
            await self.log.logger(f"Error happened during request type query data parsing", False, "error", True)
            return ConversationHandler.END
