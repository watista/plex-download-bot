#!/usr/bin/python3

import os
import re
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from src.states import MOVIE_OPTION, MOVIE_NOTIFY, MOVIE_UPGRADE, MOVIE_UPGRADE_INFO, MOVIE_UPGRADE_INFO_OTHER
from src.commands.media import Media, chosen_media, title_and_year
from src.services.radarr import Radarr
from src.log import get_logger


log = get_logger(__name__)


class Movie(Media):
    """ Specific class for movie handling """

    filter_fields = ("id", "movieFileId", "monitored", "status")

    def __init__(self, args, logger, functions, telegram, faults):
        super().__init__(args, logger, functions, telegram, faults, Radarr(logger),
                         "film", os.getenv('MOVIE_FOLDERS'), MOVIE_OPTION)

    async def get_media_states(self) -> dict:
        """ Function that defines the states """

        # Only a movie that is in Radarr has an id. Do not use monitored for this:
        # it is also False for a movie in Radarr that has been unmonitored.
        return {
            "downloading": {
                "outcome": "downloading",
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
            "not_available": {
                "outcome": "not_released",
                "condition": lambda movie, _: not movie.get("id") and movie.get("status") != "released",
                "message": "Op dit moment is {title} nog niet downløadbaar, hij is toegevoegd aan de te-downløaden-lijst. Zodra {title} gedownløad kan worden gebeurt dit automatisch.",
                "action": "start_download",
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "not_available_already_requested": {
                "outcome": "not_released",
                "condition": lambda movie, _: movie.get("movieFileId") == 0 and movie.get("monitored") and movie.get("status") != "released",
                "message": "Op dit moment is {title} nog niet downløadbaar, hij is toegevoegd aan de te-downløaden-lijst. Zodra {title} gedownløad kan worden gebeurt dit automatisch.",
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "available_to_download": {
                "outcome": "download_started",
                "condition": lambda movie, _: not movie.get("id") and movie.get("status") == "released",
                "message": "De downløad voor {title} is nu gestart, gemiddeld duurt het 1 uur voordat een film online staat, nog even geduld 😄",
                "action": "start_download",
                "extra_action": "scan_missing_media",
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "available_to_download_but": {
                "outcome": "no_download_match",
                "condition": lambda movie, _: movie.get("movieFileId") == 0 and movie.get("monitored") and movie.get("status") == "released",
                "message": "Zo te zien is {title} wel al downloadbaar, alleen is er al een tijdje geen downløad-match gevonden. Misschien wordt er nog een downløad-match gevonden maar het kan ook zijn dat dit nog lang gaat duren of helemaal niet meer. Wil je deze film echt super graag, dan kan je contact opnemen met de serverbeheerder om te kijken of de film toch handmatig gedownløad kan worden.",
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "unmonitored": {
                "outcome": "unmonitored",
                "condition": lambda movie, _: movie.get("movieFileId") == 0 and not movie.get("monitored"),
                "message": "{title} staat op dit moment aangemerkt als 'niet downløaden', dit kan verschillende redenen hebben. De serverbeheerder is op de hoogte gesteld van de aanvraag en zal deze beoordelen en er bij je op terug komen.",
                "inform_unmonitored": True,
                "state_message": True,
                "next_state": MOVIE_NOTIFY
            },
            "already_downloaded": {
                "outcome": "already_downloaded",
                "condition": lambda movie, _: movie.get("movieFileId", 0) != 0,
                "next_state": MOVIE_UPGRADE
            },
        }

    async def create_download_payload(self, data: dict, folder: str, monitor: bool) -> dict:
        """ Generates the download payload for Radarr; a missing field falls through to the wrapper as a Bug """

        payload = {
            "qualityProfileId": 7,
            "monitored": monitor,
            "tmdbId": data["tmdbId"],
            "rootFolderPath": folder
        }

        return payload

    async def media_upgrade(self, update: Update, context: CallbackContext) -> Optional[int]:
        """ Handles if the user wants the media to be quality upgraded """

        # Answer query
        await update.callback_query.answer()
        choice = "no" if update.callback_query.data == "film_upgrade_no" else "yes"
        log.info(f"something wrong with the download of {title_and_year(chosen_media(context.user_data))}: {choice}",
                 event="quality_request", choice=choice, media=chosen_media(context.user_data))

        if choice == "no":
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

    async def media_upgrade_info(self, update: Update, context: CallbackContext) -> Optional[int]:
        """ Handles the specific info about the media upgrade """

        # Answer query
        await update.callback_query.answer()
        reason = update.callback_query.data
        log.info(f"quality request for {title_and_year(chosen_media(context.user_data))}: {reason}",
                 event="quality_request", reason=reason, media=chosen_media(context.user_data))

        if reason == "other":
            #
            await self.function.send_message(f"Beschrijf wat er mis is met de film a.u.b.", update, context)
            return MOVIE_UPGRADE_INFO_OTHER

        # Send the confirmation message and notify option
        await self.telegram.send_admin_message(f"*⚠️ User did a quality request for {context.user_data['media_data']['title']} ({context.user_data['media_data']['tmdbId']}) ⚠️*\nReason: {reason}\nGebruiker: {context.user_data['gebruiker']}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}",
                                               "quality request for a movie")
        await self.function.send_message(f"Duidelijk! De film zal zo snel mogelijk worden geüpgraded. Je ontvangt een bericht zodra dit is gedaan.", update, context)
        return ConversationHandler.END

    async def media_upgrade_info_other(self, update: Update, context: CallbackContext) -> None:
        """ Handles the specific info about the media upgrade """

        # The description as the user typed it
        text = update.message.text
        log.info(f"quality request for {title_and_year(chosen_media(context.user_data))}: other: '{text}'",
                 event="quality_request", reason="other", text=text, media=chosen_media(context.user_data))

        # Send the confirmation message and notify option
        await self.telegram.send_admin_message(f"*⚠️ User did a quality request for {context.user_data['media_data']['title']} ({context.user_data['media_data']['tmdbId']}) ⚠️*\nReason: {self.function.sanitize_text(text)}\nGebruiker: {context.user_data['gebruiker']}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}",
                                               "quality request for a movie")
        await self.function.send_message(f"Duidelijk! De film zal zo snel mogelijk worden geüpgraded. Je ontvangt een bericht zodra dit is gedaan.", update, context)
        return ConversationHandler.END
