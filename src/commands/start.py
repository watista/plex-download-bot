#!/usr/bin/python3

import json

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext


class Start:

    def __init__(self, logger, functions, serie, movie, account):

        # Set default values
        self.log = logger
        self.function = functions
        self.serie = serie
        self.movie = movie
        self.account = account


    async def start_msg(self, update: Update, context: CallbackContext) -> None:

        # Set start log
        await self.log.logger(f"Function start.start_msg() started for user_id: {update.effective_chat.id}, username: {update.effective_chat['username']}", False, "info", False)

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

        # Set finish log
        await self.log.logger(f"Function start.start_msg() finished for user_id: {update.effective_chat.id}, username: {update.effective_chat['username']}", False, "info", False)


    async def verification(self, update: Update, context: CallbackContext, data: str) -> None:

        # Set start log
        await self.log.logger(f"Function start.verification() started for user_id: {update.effective_chat.id}, username: {update.effective_chat['username']}", False, "info", False)

        # Load JSON file
        with open("users.json", "r") as file:
            json_data = json.load(file)

        # Check if user_id is known in json
        if update.effective_chat.id in json_data["user_id"].values():
            # User is already verified, can go on to requesting
            if data == "serie_request":
                await self.serie.start(update, context)
            elif data == "movie_request":
                await self.movie.start(update, context)
            elif data == "account_request":
                await self.account.start(update, context)
            else:
                # Send msg to user + logging
                await self.function.send_message(f"*😵 *Oeps, daar ging iets fout*\n\nWouter is op de hoogte gesteld van het probleem, je kan het nogmaals proberen in hoop dat het dan wel werkt, of je kan het op een later moment proberen.", update, context)
                await self.log.logger(f"Error happened during query data parsing", False, "error", True)
        else:
            # Ask for user password
            await self.function.send_message(f"geef wachtwoord", update, context)

        # Set finish log
        await self.log.logger(f"Function start.verification() finished for user_id: {update.effective_chat.id}, username: {update.effective_chat['username']}", False, "info", False)
