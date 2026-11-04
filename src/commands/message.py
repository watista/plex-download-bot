#!/usr/bin/python3

import asyncio
import os
import json
import aiofiles
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from src.conversation import command_or_choice_line
from src.log import get_logger
from src.states import MESSAGE_ID, MESSAGE_MESSAGE, MESSAGE_ALL_ID, ADD_MOVIE, ADD_MOVIE_USER


log = get_logger(__name__)


class Message:

    def __init__(self, args, logger, functions, telegram):

        # Set default values
        self.args = args
        self.log = logger
        self.function = functions
        self.telegram = telegram
        self.data_json = "data.json" if args.env == "live" else "data.dev.json"

    async def _load_data(self) -> dict:
        async with aiofiles.open(self.data_json, "r") as file:
            data = json.loads(await file.read())

        return data

    async def _save_data(self, data: dict) -> None:
        async with aiofiles.open(self.data_json, "w") as file:
            await file.write(json.dumps(data, indent=4))

    @staticmethod
    def _is_broadcast_subscribed(data: dict, user_id: str) -> bool:
        # Default: subscribed unless explicitly turned off
        subs = data.get("update_messages", {})
        if not isinstance(subs, dict):
            return True
        return subs.get(user_id, True) is True

    async def updates_subscribe(self, update: Update, context: CallbackContext) -> int:
        """ /aanmelden_updates, or its button in the start menu """
        return await self._set_general_updates(update, context, True)

    async def updates_unsubscribe(self, update: Update, context: CallbackContext) -> int:
        """ /afmelden_updates, or its button in the start menu """
        return await self._set_general_updates(update, context, False)

    async def _set_general_updates(self, update: Update, context: CallbackContext, on: bool) -> int:
        """ Turns the general updates of the Beheerder on or off for this user """
        log.info(**command_or_choice_line(update))
        if update.callback_query:
            await update.callback_query.answer()

        data = await self._load_data()
        subs = data.setdefault("update_messages", {})
        user_id = str(update.effective_user.id)
        was_subscribed = subs.get(user_id, True) is True
        subs[user_id] = on
        await self._save_data(data)

        choice = "on" if on else "off"
        changed = was_subscribed != on
        log.info(f"general updates {choice}: {'changed' if changed else f'already {choice}'}", event="general_updates",
                 choice=choice, outcome="changed" if changed else "unchanged")

        if on:
            text = ("Je bent nu aangemeld voor algemene updates van de serverbeheerder." if changed
                    else "Je stond al aangemeld voor algemene updates van de serverbeheerder.")
        else:
            text = ("Je bent nu afgemeld voor algemene updates van de serverbeheerder." if changed
                    else "Je stond al afgemeld voor algemene updates van de serverbeheerder.")
        await self.function.send_message(text, update, context)
        return ConversationHandler.END


    async def message_start(self, update: Update, context: CallbackContext) -> int:

        log.info("admin command /message", event="admin_command", command="/message")

        # Send the message
        await self.function.send_message(f"Naar welk Telegram ID wil je een bericht sturen?", update, context)

        # Return to the next state
        return MESSAGE_ID


    async def message_id(self, update: Update, context: CallbackContext) -> int:

        # Check if ID is only int
        try:
            send_id = int(update.message.text)
        except (TypeError, ValueError):
            log.info("/message: the recipient is not a number", event="admin_command", command="/message",
                     outcome="not_a_number")
            await self.function.send_message("Foutieve input, geef alleen cijfers op", update, context)
            return MESSAGE_ID
        log.info(f"/message: recipient {send_id}", event="admin_command", command="/message", recipient=send_id)

        # Set context data MSG id based on live/dev
        context.user_data["id_to_send_msg"] = send_id if self.args.env == "live" else os.getenv('CHAT_ID_ADMIN')

        # Send the message
        await self.function.send_message(f"Wat is het bericht dat je wilt sturen?", update, context)

        # Return to the next state
        return MESSAGE_MESSAGE


    async def message_send(self, update: Update, context: CallbackContext) -> None:

        # The text as the Beheerder typed it: the line user_message of the receiver leaves it out
        recipient = context.user_data["id_to_send_msg"]
        log.info(f"/message to {recipient}: '{update.message.text}'", event="admin_command", command="/message",
                 recipient=recipient, text=update.message.text)

        # Send the message to designated user and pop data: underscore pairs become italic,
        # and send falls back to plain text if Telegram rejects the HTML
        delivery = await self.telegram.send_user_message(
            context.user_data["id_to_send_msg"], "message", self.function.format_admin_broadcast_html(update.message.text))
        context.user_data.pop("id_to_send_msg", None)

        # Send the message
        await self.function.send_message(
            "Bericht is verstuurd." if delivery.delivered else f"Bericht is niet afgeleverd: {delivery.reason}",
            update, context)

        # End convo
        return ConversationHandler.END


    async def message_all(self, update: Update, context: CallbackContext) -> int:

        log.info("admin command /message_all", event="admin_command", command="/message_all")

        # Send the message
        await self.function.send_message(f"Wat is het bericht dat je wilt sturen?", update, context)

        # Return to the next state
        return MESSAGE_ALL_ID


    async def message_all_id(self, update: Update, context: CallbackContext) -> None:

        # Underscore pairs become italic, and send falls back to plain text if Telegram rejects the HTML
        html_body = self.function.format_admin_broadcast_html(update.message.text)

        # Send the message to all users
        # if dev: only to the Beheerder
        if self.args.env != "live":
            delivery = await self.telegram.send_user_message(os.getenv("CHAT_ID_ADMIN"), "broadcast", html_body)
            sent, not_delivered, skipped_users = int(delivery.delivered), int(not delivery.delivered), []
            reply = "Bericht is verstuurd." if delivery.delivered else f"Bericht is niet afgeleverd: {delivery.reason}"
        else:
            # Load JSON file
            json_data = await self._load_data()

            # Send the message for all users. One that does not arrive is a user_message on WARNING.
            sent = 0
            not_delivered = 0
            skipped_users = []

            for key in json_data.get("user_id", {}):
                if not self._is_broadcast_subscribed(json_data, str(key)):
                    # Value format is "gebruiker, username"
                    name_parts = [part.strip() for part in json_data["user_id"].get(str(key), "Unknown, Unknown").split(",", 1)]
                    gebruiker = name_parts[0]
                    username = name_parts[1] if len(name_parts) > 1 else "Unknown"
                    skipped_users.append(f"{username} ({gebruiker})")
                    continue
                delivery = await self.telegram.send_user_message(int(key), "broadcast", html_body)
                if delivery.delivered:
                    sent += 1
                else:
                    not_delivered += 1
                await asyncio.sleep(1)

            skipped_overview = "".join(f"\n- {user}" for user in skipped_users)
            reply = f"Berichten zijn verstuurd.\n\nVerstuurd naar: {sent}\nNiet afgeleverd: {not_delivered}\nOvergeslagen (afgemeld): {len(skipped_users)}{skipped_overview}"

        # The text as the Beheerder typed it, and who got it
        text = update.message.text
        log.info(f"/message_all: '{text}': sent {sent}, not delivered {not_delivered}, skipped {len(skipped_users)}",
                 event="admin_command", command="/message_all", text=text, sent=sent, not_delivered=not_delivered,
                 skipped=len(skipped_users))

        # Send the message
        await self.function.send_message(reply, update, context)

        # End convo
        return ConversationHandler.END


    async def add_movie(self, update: Update, context: CallbackContext) -> int:

        log.info("admin command /add_movie", event="admin_command", command="/add_movie")

        # Send the message
        await self.function.send_message(f"Voor welk Telegram ID wil je een film toevoegen?", update, context)

        # Return to the next state
        return ADD_MOVIE


    async def add_movie_user(self, update: Update, context: CallbackContext) -> int:

        # Check if ID is only int
        try:
            add_id = int(update.message.text)
        except (TypeError, ValueError):
            log.info("/add_movie: the recipient is not a number", event="admin_command", command="/add_movie",
                     outcome="not_a_number")
            await self.function.send_message("Foutieve input, geef alleen cijfers op", update, context)
            return ADD_MOVIE
        log.info(f"/add_movie: recipient {add_id}", event="admin_command", command="/add_movie", recipient=add_id)

        # Set context data MSG id based on live/dev
        context.user_data["user_to_add_movie"] = add_id

        # Send the message
        await self.function.send_message(f"Wat is het TMDB ID van de film?", update, context)

        # Return to the next state
        return ADD_MOVIE_USER


    async def add_movie_id(self, update: Update, context: CallbackContext) -> None:

        # Check if ID is only int
        try:
            tmdb_to_add_movie = int(update.message.text)
        except (TypeError, ValueError):
            log.info("/add_movie: the tmdbId is not a number", event="admin_command", command="/add_movie",
                     outcome="not_a_number")
            await self.function.send_message("Foutieve input, geef alleen cijfers op", update, context)
            return ADD_MOVIE_USER
        recipient = context.user_data["user_to_add_movie"]
        log.info(f"/add_movie: tmdb {tmdb_to_add_movie} for {recipient}", event="admin_command", command="/add_movie",
                 recipient=recipient, tmdb_id=tmdb_to_add_movie)

        # Load JSON file
        async with aiofiles.open(self.data_json, "r") as file:
            json_data = json.loads(await file.read())

        # Add / overwrite movie entry
        json_data["notify_list"][str(context.user_data["user_to_add_movie"])]["film"][tmdb_to_add_movie] = int(time.time())

        # Write back to JSON
        async with aiofiles.open(self.data_json, "w") as file:
            await file.write(json.dumps(json_data, indent=4))

        # Send the message
        await self.function.send_message(f"Film ID {tmdb_to_add_movie} is toegevoegd voor user {context.user_data['user_to_add_movie']}", update, context)

        context.user_data.pop("user_to_add_movie", None)

        # End convo
        return ConversationHandler.END

