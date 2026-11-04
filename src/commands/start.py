#!/usr/bin/python3

import json
import asyncio
import aiofiles
from datetime import datetime
from typing import Union, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from src.conversation import command_of, command_or_choice_line
from src.log import get_logger
from src.states import VERIFY, REQUEST_ACCOUNT, REQUEST_MOVIE, REQUEST_SERIE, VERIFY_PWD


log = get_logger(__name__)

# The options of the start menu that need Plex, Sonarr, Radarr and Transmission: in maintenance mode they get the
# maintenance message
NEEDS_PRIMARY = ("movie_request", "serie_request", "aanmelden_serie", "afmelden_serie")

# Wrong passwords after which a Bezoeker is blocked
MAX_LOGIN_TRIES = 3


class Start:

    def __init__(self, args, logger, functions, maintenance=None, telegram=None):

        # Set default values
        self.log = logger
        self.function = functions
        self.mode = getattr(args, "mode", "normal")
        self.maintenance = maintenance
        self.telegram = telegram

        # Set data.json/stats.json file based on live/dev arg
        self.data_json = "data.json" if args.env == "live" else "data.dev.json"
        self.stats_json = "stats.json" if args.env == "live" else "stats.dev.json"

    async def start_msg(self, update: Update, context: CallbackContext) -> int:
        """ /start: shows the start menu """
        log.info(**command_or_choice_line(update))
        return await self.show_menu(update, context)

    async def outside_conversation(self, update: Update, context: CallbackContext) -> int:
        """ Text while no Gesprek runs: shows the start menu.

        The text gets no line: it may be a password, sent again after the Gesprek expired.
        """
        log.info("sent text outside a conversation: showed /start", event="outside_conversation", outcome="start_shown")
        return await self.show_menu(update, context)

    async def show_menu(self, update: Update, context: CallbackContext) -> int:
        """ Sends the start menu """

        # Clear previous choices
        context.user_data.pop("media_option", None)

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
            ],
            [
                InlineKeyboardButton("✅ Serie updates", callback_data="aanmelden_serie"),
                InlineKeyboardButton("❌ Serie updates", callback_data="afmelden_serie"),
            ],
            [
                InlineKeyboardButton("✅ Algemene updates", callback_data="aanmelden_updates"),
                InlineKeyboardButton("❌ Algemene updates", callback_data="afmelden_updates"),
            ]
        ])

        # Send the message with the keyboard options
        await self.function.send_gif(f"*🔥🤖 Wouter Thuis-Server Bot 🤖🔥*\n\nWaar kan ik je vandaag mee helpen?\n\n_Stuur /stop op elk moment om de bot te stoppen_", open("files/watch-serie.gif", "rb"), update, context, reply_markup)

        # Return to the next state
        return VERIFY

    async def verification(self, update: Update, context: CallbackContext) -> Optional[int]:
        """ /aanmelden_serie, /afmelden_serie, or an option of the start menu that needs a login """

        # The option: the button of the start menu, or the command without its slash
        if update.callback_query:
            context.user_data["media_option"] = update.callback_query.data
            await update.callback_query.answer()
        else:
            context.user_data["media_option"] = command_of(update).removeprefix("/")

        # Load JSON file
        async with aiofiles.open(self.data_json, "r") as file:
            json_data = json.loads(await file.read())
        blocked = str(update.effective_user.id) in json_data["blocked_users"]
        known = not blocked and str(update.effective_user.id) in json_data["user_id"]

        # In maintenance mode a Gebruiker gets the maintenance message right away, a Bezoeker after logging in
        log.info(**command_or_choice_line(update, maintenance=known and self.in_maintenance(context.user_data["media_option"])))

        # Check if user is blocked
        if blocked:
            log.info("login refused: on the blocklist", event="login", outcome="refused")
            await self.function.send_message(f"Je bent geblokkeerd om deze bot te gebruiken, als je denkt dat dit een fout is kan je contact opnemen met de serverbeheerder.", update, context)
            await self.telegram.send_admin_message(f"*ℹ️ A blocked user tried to login ℹ️*\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}",
                                                   "blocked user tried to log in")
            # Finish the conversation
            return ConversationHandler.END

        # Check if user_id is already known and verified
        if known:

            # Set gebruikernaam if not set
            if not context.user_data.get("gebruiker"):
                context.user_data["gebruiker"] = json_data.get("user_id", {}).get(str(update.effective_user.id)).split(",", 1)[0].strip()

            # write to stats.json
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

        # Ask for user password if not yet verified
        await self.function.send_message(f"Zo te zien is dit de eerste keer dat je gebruik maakt van deze bot. Om gebruik te maken van de bot heb je een wachtwoord nodig (wachtwoord vergeten? vraag deze opnieuw aan bij de serverbeheerder).\n\nVoer nu je wachtwoord in:\n\n stuur /stop om opnieuw te beginnen.", update, context)

        # Set amount on login tries
        context.user_data["login_tries"] = 0

        # Return to the next state
        return VERIFY_PWD

    async def verify_pwd(self, update: Update, context: CallbackContext) -> Optional[int]:

        # Load JSON file
        async with aiofiles.open(self.data_json, "r") as file:
            json_data = json.loads(await file.read())

        # Check if given password is known in json. Only the outcome gets a line, never the password.
        for key, value in json_data["users"].items():
            if value == update.message.text:
                log.info(f"logged in as {key}", event="login", outcome="success", logged_in_as=key)
                await self.telegram.send_admin_message(f"*ℹ️ First time login for user ℹ️*\nGebruiker: {key}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}",
                                                       "first login")
                await self.function.send_message(f"Je wachtwoord klopt!\n\nJe bent nu ingelogd als gebruiker: {key}", update, context)
                await asyncio.sleep(1)

                # Set username to user_context
                context.user_data["gebruiker"] = key

                # Write user_id to json
                json_data["user_id"][str(update.effective_user.id)] = f"{key}, {update.effective_user.first_name}"
                # Default: user is subscribed to general update messages
                json_data.setdefault("update_messages", {})
                json_data["update_messages"][str(update.effective_user.id)] = True
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
        attempt = context.user_data["login_tries"]

        # add user to blocked_json
        if attempt >= MAX_LOGIN_TRIES:
            # Send message and add to blocklist
            log.info(f"wrong password (attempt {attempt} of {MAX_LOGIN_TRIES}): blocked", event="login",
                     outcome="blocked", attempt=attempt)
            await self.telegram.send_admin_message(f"*ℹ️ User has been blocked ℹ️*\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}",
                                                   "user blocked")
            await self.function.send_message(f"Je hebt 3 keer het verkeerde wachtwoord ingevoerd, je bent nu geblokkerd. Neem contact op met de serverbeheerder om deze blokkade op te heffen.", update, context)
            json_data["blocked_users"][str(
                update.effective_user.id)] = update.effective_user.first_name
            async with aiofiles.open(self.data_json, "w") as file:
                await file.write(json.dumps(json_data, indent=4))
            # Finish the conversation
            return ConversationHandler.END

        # Wrong password
        log.info(f"wrong password (attempt {attempt} of {MAX_LOGIN_TRIES})", event="login", outcome="wrong_password",
                 attempt=attempt)
        await self.function.send_message(f"Het opgegeven wachtwoord is onjuist, je hebt nog {MAX_LOGIN_TRIES - attempt} pogingen voordat je toegang wordt geblokkeerd.", update, context)

        # Return and retry the verify_pwd state
        await asyncio.sleep(1)
        await self.function.send_message(f"Voer nu je wachtwoord in:", update, context)
        return VERIFY_PWD

    async def account_request(self, update: Update, context: CallbackContext) -> Optional[int]:
        """ The button for a new account in the start menu: no login needed, also not in maintenance mode """
        log.info(**command_or_choice_line(update))
        return await self.parse_request(update, context)

    def in_maintenance(self, option: str | None) -> bool:
        """ True when this option of the start menu gets the maintenance message.

        account_request, info and aanmelden/afmelden_updates continue to work in maintenance mode, because they
        only touch data.json and Telegram.
        """
        return self.mode == "maintenance" and option in NEEDS_PRIMARY

    async def parse_request(self, update: Update, context: CallbackContext) -> Optional[int]:

        if update.callback_query:
            context.user_data["media_option"] = update.callback_query.data
            await update.callback_query.answer()

        # In maintenance mode, intercept the options that need Plex/Sonarr/Radarr
        if self.in_maintenance(context.user_data.get("media_option")):
            return await self.maintenance.notice(update, context)

        if context.user_data["media_option"] == "account_request":
            await self.function.send_message(f"Leuk dat je interesse hebt in Plęx. Voordat er een account voor je aangemaakt kan worden, is er eerst wat informatie van je nodig.", update, context)
            await asyncio.sleep(1)
            await self.function.send_message(f"Om te beginnen, wat is je naam?", update, context)
            return REQUEST_ACCOUNT
        elif context.user_data["media_option"] == "serie_request":
            context.user_data["media_type"] = "serie"
            await self.function.send_message(f"Welke serie wil je graag op Plęx zien?", update, context)
            return REQUEST_SERIE
        elif context.user_data["media_option"] == "movie_request":
            context.user_data["media_type"] = "movie"
            await self.function.send_message(f"Welke film wil je graag op Plęx zien?", update, context)
            return REQUEST_MOVIE
        elif context.user_data["media_option"] == "aanmelden_serie":
            return await self.subscribe.aanmelden(update, context)
        elif context.user_data["media_option"] == "afmelden_serie":
            return await self.subscribe.afmelden(update, context)
        else:
            # Send msg to user + logging
            await self.function.send_message(f"*😵 Oeps, daar ging iets fout*\n\nDe serverbeheerder is op de hoogte gesteld van het probleem, je kan het nog een keer proberen in de hoop dat het dan wel werkt, of je kan het op een later moment nogmaals proberen.", update, context)
            await self.log.logger(f"Error happened during request type query data parsing", False, "error", True)
            return ConversationHandler.END
