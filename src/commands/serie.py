#!/usr/bin/python3

import asyncio
import os
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from src.states import SERIE_OPTION, SERIE_NOTIFY, SERIE_UPGRADE, SERIE_UPGRADE_OPTION, SERIE_UPGRADE_INFO
from src.commands.media import Media
from src.services.sonarr import Sonarr


class Serie(Media):
    """ Specific class for serie handling """

    def __init__(self, args, logger, functions):
        super().__init__(args, logger, functions, Sonarr(logger),
                         "serie", os.getenv('SERIE_FOLDERS'), SERIE_OPTION)

    async def get_media_states(self) -> dict:
        """ Function that defines the states """

        return {
            "downloading": {
                "condition": lambda serie, torrents: any(serie["title"].lower() in t.name.lower() for t in torrents),
                "message": "{title} wordt op dit moment al gedownload, nog even geduld 😄",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "not_available": {
                "condition": lambda serie, _: not serie.get("path") and serie.get("status") == "upcoming",
                "size_check": True,
                "message": "Op dit moment is {title} nog niet downloadbaar, hij is toegevoegd aan de te-downloaden-lijst. Zodra {title} gedownload kan worden gebeurt dit automatisch.",
                "action": "start_download",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "not_available_already_requested": {
                "condition": lambda serie, _: serie.get("path") and serie.get("status") == "upcoming",
                "message": "Op dit moment is {title} nog niet downloadbaar, hij is toegevoegd aan de te-downloaden-lijst. Zodra {title} gedownload kan worden gebeurt dit automatisch.",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "available_to_download": {
                "condition": lambda serie, _: not serie.get("path") and serie.get("status") != "upcoming",
                "size_check": True,
                "message": "De download voor {title} is nu gestart, gemiddeld duurt het 1 uur voordat een serie online staat, nog even geduld 😄",
                "action": "start_download",
                "extra_action": "scan_missing_media",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "unmonitored": {
                "condition": lambda serie, _: not serie.get("monitored"),
                "message": "{title} staat op dit moment aangemerkt als 'niet downloaden', dit kan verschillende redenen hebben. De serverbeheerder is op de hoogte gesteld van de aanvraag en zal deze beoordelen en er bij je op terug komen.",
                "inform_unmonitored": True,
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "already_downloaded": {
                "condition": lambda serie, _: serie.get("path"),
                "next_state": SERIE_UPGRADE
            }
        }

    async def create_download_payload(self, data: dict, folder: str, monitor: bool) -> dict:
        """ Generates the download payload for Radarr """

        payload = {
            "title": data['title'],
            "qualityProfileId": 7,
            "monitored": monitor,
            "tvdbId": data['tvdbId'],
            "rootFolderPath": folder,
            "addOptions": {
                "ignoreEpisodesWithFiles": False,
                "ignoreEpisodesWithoutFiles": False,
                "searchForMissingEpisodes": True
            }
        }

        return payload

    async def media_upgrade(self, update: Update, context: CallbackContext) -> Optional[int]:
        """ Handles if the user wants the media to be quality upgraded """

        # Answer query
        await update.callback_query.answer()

        # Finish conversation if chosen
        if update.callback_query.data == f"serie_upgrade_no":
            await self.function.send_message(f"Oke, bedankt voor het gebruiken van deze bot. Wil je nog iets anders downloaden? Stuur dan /start", update, context)
            return ConversationHandler.END
        else:
            # Ask for specific info about quality
            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "Slechte kwaliteit (bijv. 720p)", callback_data="quality")
                ],
                [
                    InlineKeyboardButton(
                        "Ingebrande (chinese) ondertiteling", callback_data="subs")
                ],
                [
                    InlineKeyboardButton(
                        "Reclame/Logo's in het scherm", callback_data="ads")
                ],
                [
                    InlineKeyboardButton("Overig", callback_data="other")
                ]
            ])

            # Send the message with the keyboard options
            await self.function.send_message(f"Kan je aangeven wat er precies mis is met de kwaliteit van de serie?", update, context, reply_markup)

            # Return to the next state
            return SERIE_UPGRADE_INFO

    async def media_upgrade_info(self, update: Update, context: CallbackContext) -> int:
        """ Handles the specific info about the media upgrade """

        # Answer query
        self.callback_data = update.callback_query.data
        await update.callback_query.answer()

        # Aks question which season/episode needs to be upgrade
        await self.function.send_message(f"Check, en kan je aangeven om welk seizoen en/of episode het gaat? (bijvoorbeeld seizoen 1, episode 4 of episode 1 t/m 8 van seizoen 3)", update, context)
        return SERIE_UPGRADE_OPTION

    async def media_upgrade_option(self, update: Update, context: CallbackContext) -> None:
        """ Handles the answer for which season/episode the serie should be upgraded """

        # Send the confirmation message and notify option
        await self.log.logger(f"*⚠️ User did a quality request for {self.media_data['title']} ({self.media_data['tmdbId']}) ⚠️*\nSeason/Episode: {self.function.sanitize_text(update.message.text)}\nReason: {self.callback_data}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")
        await self.function.send_message(f"Duidelijk! De aangegeven seizoenen/episodes zullen worden geupgrade, dit duurt meestal ongeveer 1 dag.", update, context)
        return ConversationHandler.END
