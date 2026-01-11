#!/usr/bin/python3

import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from src.states import MESSAGE_ID, MESSAGE_MESSAGE


class Message:

    def __init__(self, args, logger, functions):

        # Set default values
        self.args = args
        self.log = logger
        self.function = functions


    async def message_start(self, update: Update, context: CallbackContext) -> int:

        # Debug usage log
        await self.log.logger(f"User started bot with /message - Username: {update.effective_user.first_name} - User ID: {update.effective_user.id}", False, "debug", False)

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

        # Send the message to designated user
        await self.function.send_message(update.message.text, context.user_data["id_to_send_msg"], context, None, "MarkdownV2", False)

        # Send the message
        await self.function.send_message(f"Bericht is verstuurd.", update, context)

        # End convo
        return ConversationHandler.END
