#!/usr/bin/python3

import asyncio
import os
import json
import aiofiles
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from telegram.error import TelegramError
from src.states import MESSAGE_ID, MESSAGE_MESSAGE, MESSAGE_ALL_ID


class Message:

    def __init__(self, args, logger, functions):

        # Set default values
        self.args = args
        self.log = logger
        self.function = functions


    async def message_start(self, update: Update, context: CallbackContext) -> int:

        # Debug usage log
        await self.log.logger(f"User started bot with /message - Gebruiker: {context.user_data["gebruiker"]} - Username: {update.effective_user.first_name} - User ID: {update.effective_user.id}", False, "debug", False)

        # Send the message
        await self.function.send_message(f"Naar welk Telegram ID wil je een bericht sturen?", update, context)

        # Return to the next state
        return MESSAGE_ID


    async def message_id(self, update: Update, context: CallbackContext) -> int:

        # Check if ID is only int
        try:
            send_id = int(update.message.text)
        except (TypeError, ValueError):
            await self.function.send_message("Foutieve input, geef alleen cijfers op", update, context)
            return MESSAGE_ID

        # Set context data MSG id based on live/dev
        context.user_data["id_to_send_msg"] = send_id if self.args.env == "live" else os.getenv('CHAT_ID_ADMIN')

        # Send the message
        await self.function.send_message(f"Wat is het bericht dat je wilt sturen?", update, context)

        # Return to the next state
        return MESSAGE_MESSAGE


    async def message_send(self, update: Update, context: CallbackContext) -> None:

        # Send the message to designated user and pop data
        await self.function.send_message(update.message.text, context.user_data["id_to_send_msg"], context, None, "MarkdownV2", False)
        context.user_data.pop("id_to_send_msg", None)

        # Send the message
        await self.function.send_message(f"Bericht is verstuurd.", update, context)

        # End convo
        return ConversationHandler.END


    async def message_all(self, update: Update, context: CallbackContext) -> int:

        # Debug usage log
        await self.log.logger(f"User started bot with /message_all - Gebruiker: {context.user_data["gebruiker"]} - Username: {update.effective_user.first_name} - User ID: {update.effective_user.id}", False, "debug", False)

        # Send the message
        await self.function.send_message(f"Wat is het bericht dat je wilt sturen?", update, context)

        # Return to the next state
        return MESSAGE_ALL_ID


    async def message_all_id(self, update: Update, context: CallbackContext) -> None:

        # Send the message to all users
        self.data_json = "data.json" if self.args.env == "live" else "data.dev.json"

        # if dev
        if self.args.env != "live":
            await self.function.send_message(update.message.text, os.getenv('CHAT_ID_ADMIN'), context, None, "MarkdownV2", False)
            await self.function.send_message(f"Bericht is verstuurd.", update, context)
            return ConversationHandler.END

        # Load JSON file
        async with aiofiles.open(self.data_json, "r") as file:
            json_data = json.loads(await file.read())

        # Send the message for all users
        for key in json_data["user_id"]:
            try:
                await self.function.send_message(update.message.text, key, context, None, "MarkdownV2", False)
            except TelegramError as e:
                await self.log.logger(f"Error happened during message_all to {key}, see the logs for more info.", False, "error")
                await self.log.logger(f"Exception: {e}", False, "error", False)
            await asyncio.sleep(1)

        # Send the message
        await self.function.send_message(f"Berichten zijn verstuurd.", update, context)

        # End convo
        return ConversationHandler.END
