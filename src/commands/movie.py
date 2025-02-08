#!/usr/bin/python3

import asyncio
import os
import json
from transmission_rpc import Client
from typing import Optional
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext, ConversationHandler

from src.states import MOVIE_OPTION, MOVIE_NOTIFY, MOVIE_UPGRADE
from src.commands.media import Media
from src.services.radarr import Radarr


class Movie(Media):
    """ Specific class for movie handling """

    def __init__(self, args, logger, functions):
        super().__init__(args, logger, functions, Radarr(logger), "film", os.getenv('MOVIE_FOLDERS'), MOVIE_OPTION)


    async def get_media_states(self) -> dict:
        """ Function that defines the states """

        return {
            "downloading": {
                "condition": lambda movie, torrents: any(movie["title"].lower() in t.name.lower() for t in torrents),
                "message": "{title} wordt op dit moment al gedownload, nog even geduld 😄",
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "not_available_not_monitored": {
                "condition": lambda movie, _: movie.get("movieFileId") == 0 and not movie.get("monitored") and movie.get("status") != "released",
                "message": "Op dit moment is {title} nog niet downloadbaar, hij is toegevoegd aan de te-downloaden-lijst. Zodra {title} gedownload kan worden gebeurt dit automatisch.",
                "action": "start_download",
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "not_available_already_requested": {
                "condition": lambda movie, _: movie.get("movieFileId") == 0 and movie.get("monitored") and movie.get("status") != "released",
                "message": "Op dit moment is {title} nog niet downloadbaar, hij is toegevoegd aan de te-downloaden-lijst. Zodra {title} gedownload kan worden gebeurt dit automatisch.",
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "available_to_download": {
                "condition": lambda movie, _: movie.get("movieFileId") == 0 and not movie.get("monitored") and movie.get("status") == "released",
                "message": "De download voor {title} is nu gestart, het kan even duren voordat deze online staat, nog even geduld 😄",
                "action": "start_download",
                "extra_action": "scan_missing_media",
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "available_to_download_but": {
                "condition": lambda movie, _: movie.get("movieFileId") == 0 and movie.get("monitored") and movie.get("status") == "released",
                "message": "Zo te zien is {title} wel al downloadbaar, alleen is er al een tijdje geen download-match gevonden. Misschien wordt er nog een download-match gevonden maar het kan ook zijn dat dit nog lang gaat duren of helemaal niet meer. Wil je deze film echt super graag, dan kan je contact opnemen met de serverbeheerder om te kijken of de film toch handmatig gedownload kan worden.",
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "already_downloaded": {
                "condition": lambda movie, _: movie.get("movieFileId") != 0 and movie.get("monitored"),
                "next_state": MOVIE_UPGRADE
            },
        }


    async def create_download_payload(self, data: dict, folder: str) -> dict:
        """ Generates the download payload for Radarr """

        payload = {
            "qualityProfileId": 7,
            "monitored": True,
            "tmdbId": data['tmdbId'],
            "rootFolderPath": folder
        }

        return payload


    async def media_upgrade(self, update: Update, context: CallbackContext) -> Optional[int]:
        """ Handles if the user wants the media to be quality upgraded """

        # Answer query
        await update.callback_query.answer()

        if update.callback_query.data == f"film_upgrade_no":
            # Finish conversation if chosen
            await self.function.send_message(f"Oke, bedankt voor het gebruiken van deze bot. Wil je nog iets anders downloaden? Stuur dan /start", update, context)
            return ConversationHandler.END
        else:
            # Send the confirmation message and notify option
            await self.log.logger(f"*ℹ️ User did a quality request for {self.media_data['title']} ({self.media_data['tmdbId']}) ℹ️*\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")
            await self.function.send_message(f"Duidelijk! De film zal worden geupgrade.", update, context)
            await asyncio.sleep(1)
            await self.ask_notify_question(update, context, "notify", f"Wil je een melding ontvangen als {self.media_data['title']} online staat?")
            return MOVIE_NOTIFY
