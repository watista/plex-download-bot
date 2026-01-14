#!/usr/bin/python3

import os
import re
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from src.states import MOVIE_OPTION, MOVIE_NOTIFY, MOVIE_UPGRADE, MOVIE_UPGRADE_INFO
from src.commands.media import Media
from src.services.radarr import Radarr


class Movie(Media):
    """ Specific class for movie handling """

    def __init__(self, args, logger, functions):
        super().__init__(args, logger, functions, Radarr(logger),
                         "film", os.getenv('MOVIE_FOLDERS'), MOVIE_OPTION)

    async def get_media_states(self) -> dict:
        """ Function that defines the states """

        return {
            "downloading": {
                # "condition": lambda movie, torrents: any(movie["title"].lower() in t.name.lower() for t in torrents),
                "condition": lambda movie, torrents: any(
                    re.search(
                        r"\b" + r"[.\s_-]+".join(
                            map(re.escape, movie["title"].split())
                        ) + r"\b",
                        t.name,
                        re.IGNORECASE
                    )
                    for t in torrents
                ),
                "message": "{title} wordt op dit moment al gedownløad, nog even geduld 😄",
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "not_available_not_monitored": {
                "condition": lambda movie, _: movie.get("movieFileId") == 0 and not movie.get("monitored") and movie.get("status") != "released",
                "message": "Op dit moment is {title} nog niet downløadbaar, hij is toegevoegd aan de te-downløaden-lijst. Zodra {title} gedownløad kan worden gebeurt dit automatisch.",
                "action": "start_download",
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "not_available_already_requested": {
                "condition": lambda movie, _: movie.get("movieFileId") == 0 and movie.get("monitored") and movie.get("status") != "released",
                "message": "Op dit moment is {title} nog niet downløadbaar, hij is toegevoegd aan de te-downløaden-lijst. Zodra {title} gedownløad kan worden gebeurt dit automatisch.",
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "available_to_download": {
                "condition": lambda movie, _: movie.get("movieFileId") == 0 and not movie.get("monitored") and movie.get("status") == "released",
                "message": "De downløad voor {title} is nu gestart, gemiddeld duurt het 1 uur voordat een film online staat, nog even geduld 😄",
                "action": "start_download",
                "extra_action": "scan_missing_media",
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "available_to_download_but": {
                "condition": lambda movie, _: movie.get("movieFileId") == 0 and movie.get("monitored") and movie.get("status") == "released",
                "message": "Zo te zien is {title} wel al downloadbaar, alleen is er al een tijdje geen downløad-match gevonden. Misschien wordt er nog een downløad-match gevonden maar het kan ook zijn dat dit nog lang gaat duren of helemaal niet meer. Wil je deze film echt super graag, dan kan je contact opnemen met de serverbeheerder om te kijken of de film toch handmatig gedownløad kan worden.",
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "already_downloaded": {
                "condition": lambda movie, _: movie.get("movieFileId") != 0 and movie.get("monitored"),
                "next_state": MOVIE_UPGRADE
            },
        }

    async def create_download_payload(self, data: dict, folder: str, monitor: bool) -> dict:
        """ Generates the download payload for Radarr """

        try:
            tmdb_id = data["tmdbId"]
        except KeyError as e:
            await self.log.logger(f"Missing required field in movie download payload: {e}", False, "error", True)
            return None

        payload = {
            "qualityProfileId": 7,
            "monitored": monitor,
            "tmdbId": tmdb_id,
            "rootFolderPath": folder
        }

        return payload

    async def media_upgrade(self, update: Update, context: CallbackContext) -> Optional[int]:
        """ Handles if the user wants the media to be quality upgraded """

        # Answer query
        await update.callback_query.answer()

        if update.callback_query.data == f"film_upgrade_no":
            # Finish conversation if chosen
            await self.function.send_message(f"Oke, bedankt voor het gebruiken van deze bot. Wil je nog iets anders downløaden? Stuur dan /start", update, context)
            return ConversationHandler.END
        else:
            # Ask for specific info about quality
            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "Slechte kwaliteit", callback_data="quality")
                ],
                [
                    InlineKeyboardButton(
                        "Ingebrande ondertiteling", callback_data="subs")
                ],
                [
                    InlineKeyboardButton(
                        "Reclame/logo's in het scherm", callback_data="ads")
                ],
                [
                    InlineKeyboardButton("Audio klopt niet", callback_data="audio")
                ],
                [
                    InlineKeyboardButton("Overig", callback_data="other")
                ]
            ])

            # Send the message with the keyboard options
            await self.function.send_message(f"Kan je aangeven wat er precies mis is met de downløad van de film?", update, context, reply_markup)

            # Return to the next state
            return MOVIE_UPGRADE_INFO

    async def media_upgrade_info(self, update: Update, context: CallbackContext) -> None:
        """ Handles the specific info about the media upgrade """

        # Answer query
        await update.callback_query.answer()

        # Send the confirmation message and notify option
        await self.log.logger(f"*⚠️ User did a quality request for {context.user_data["media_data"]['title']} ({context.user_data["media_data"]['tmdbId']}) ⚠️*\nReason: {update.callback_query.data}\nGebruiker: {context.user_data["gebruiker"]}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")
        await self.function.send_message(f"Duidelijk! De film zal worden geüpgraded, dit zal zo snel mogelijk gebeuren. Je ontvangt een bericht zodra dit is gedaan.", update, context)
        return ConversationHandler.END
