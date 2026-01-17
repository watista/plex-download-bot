#!/usr/bin/python3

import os
import re
import aiofiles
from pathlib import Path
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from src.states import SERIE_OPTION, SERIE_NOTIFY, SERIE_UPGRADE, SERIE_UPGRADE_OPTION, SERIE_UPGRADE_INFO, AANMELDEN_SERIE
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
                # "condition": lambda serie, torrents: any(serie["title"].lower() in t.name.lower() for t in torrents),
                "condition": lambda serie, torrents: any(
                    re.search(
                        r"\b" + r"[.\s_-]+".join(
                            map(re.escape, serie["title"].split())
                        ) + r"\b",
                        t.name,
                        re.IGNORECASE
                    )
                    for t in torrents
                ),
                "message": "{title} wordt op dit moment al gedownløad, nog even geduld 😄",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "not_available": {
                "condition": lambda serie, _: not serie.get("path") and serie.get("status") == "upcoming",
                "size_check": True,
                "message": "Op dit moment is {title} nog niet downløadbaar, hij is toegevoegd aan de te-downløaden-lijst. Zodra {title} gedownløad kan worden gebeurt dit automatisch.",
                "action": "start_download",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "not_available_already_requested": {
                "condition": lambda serie, _: serie.get("path") and serie.get("status") == "upcoming",
                "message": "Op dit moment is {title} nog niet downløadbaar, hij is toegevoegd aan de te-downløaden-lijst. Zodra {title} gedownløad kan worden gebeurt dit automatisch.",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "available_to_downl0ad": {
                "condition": lambda serie, _: not serie.get("path") and serie.get("status") != "upcoming",
                "size_check": True,
                "message": "De downløad voor {title} is nu gestart, gemiddeld duurt het 1 uur voordat een serie online staat, nog even geduld 😄",
                "action": "start_download",
                "extra_action": "scan_missing_media",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "unmonitored": {
                "condition": lambda serie, _: not serie.get("monitored"),
                "message": "{title} staat op dit moment aangemerkt als 'niet downløaden', dit kan verschillende redenen hebben. De serverbeheerder is op de hoogte gesteld van de aanvraag en zal deze beoordelen en er bij je op terug komen.",
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
        """ Generates the download payload for Sonarr """

        try:
            title = data["title"]
            tvdb_id = data["tvdbId"]
        except KeyError as e:
            await self.log.logger(f"Missing required field in serie download payload: {e}", False, "error", True)
            return None

        payload = {
            "title": title,
            "qualityProfileId": 7,
            "monitored": monitor,
            "tvdbId": tvdb_id,
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
            if not context.user_data['media_data'].get("ended", False):
                # Create keyboard
                reply_markup = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("Ja", callback_data="yes"),
                        InlineKeyboardButton("Nee", callback_data="no")
                    ]
                ])
                await self.function.send_message(f"Wil je updates ontvangen zodra er nieuwe afleveringen online komen? Je kan je hiervoor later altijd afmelden door /afmelden te sturen.", update, context, reply_markup)
                return AANMELDEN_SERIE
            else:
                await self.function.send_message(f"Oke, bedankt voor het gebruiken van deze bot. Wil je nog iets anders downløaden? Stuur dan /start", update, context)
                return ConversationHandler.END

        else:
            # Ask for specific info about quality
            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Missende aflevering(en)", callback_data="missing")
                ],
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
            await self.function.send_message(f"Kan je aangeven wat er precies mis is met de downløad van deze serie?", update, context, reply_markup)

            # Return to the next state
            return SERIE_UPGRADE_INFO

    async def media_upgrade_info(self, update: Update, context: CallbackContext) -> int:
        """ Handles the specific info about the media upgrade """

        # Answer query
        context.user_data["serie_upgrade_option"] = update.callback_query.data
        await update.callback_query.answer()

        # Aks question which season/episode needs to be upgrade
        await self.function.send_message(f"Om welk seizoen en/of episode gaat het?", update, context)
        return SERIE_UPGRADE_OPTION

    async def media_upgrade_option(self, update: Update, context: CallbackContext) -> None:
        """ Handles the answer for which season/episode the serie should be upgraded """

        # Send the confirmation message and notify option
        await self.log.logger(f"*⚠️ User did a quality request for {context.user_data['media_data']['title']} ({context.user_data['media_data']['tmdbId']}) ⚠️*\nSeason/Episode: {self.function.sanitize_text(update.message.text)}\nReason: {context.user_data['serie_upgrade_option']}\nGebruiker: {context.user_data['gebruiker']}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")
        await self.function.send_message(f"Duidelijk! De aangegeven seizoenen/episodes worden zo snel mogelijk gefixt. Je ontvangt een bericht zodra dit is gedaan.", update, context)
        context.user_data.pop("serie_upgrade_option", None)
        return ConversationHandler.END


    async def aanmelden(self, update: Update, context: CallbackContext) -> None:
        """ Handles if the user wants te be updated about future new serie episodes """

        # Answer query
        await update.callback_query.answer()

        # Finish conversation if chosen
        if update.callback_query.data == "no":
            await self.function.send_message(f"Oke, bedankt voor het gebruiken van deze bot. Wil je nog iets anders downløaden? Stuur dan /start", update, context)
            return ConversationHandler.END

        # Get tmdbId
        serie_id = str(context.user_data['media_data'].get("tmdbId"))
        if not serie_id or serie_id == "None":
            await self.function.send_message("Er ging iets fout bij het ophalen van data van de serie. De serverbeheerder is hiervan op de hoogte en zal dit zo snel mogelijk oplossen. Probeer het op een later moment nog is.", update, context)
            await self.log.logger(f"Error happened during parsing tmdbId in media.py, see the logs for the media JSON.", False, "error", True)
            await self.log.logger(f"Media JSON:\n{context.user_data['aanmeld_data']}", False, "error", False)
            return ConversationHandler.END

        # Load JSON
        async with aiofiles.open(self.data_json, "r") as f:
            data = json.loads(await f.read())

        # Ensure structure exists
        notify_list = data.setdefault("notify_list", {})
        user_node = notify_list.setdefault(str(update.effective_user.id), {})
        user_node.setdefault("film", {})
        user_node.setdefault("serie", {})
        user_node.setdefault("recurring_serie", {})
        serie_episode = user_node.setdefault("serie_episode", {})

        # Create/update entry
        entry = serie_episode.setdefault(serie_id, {})
        entry["started"] = True

        # Set to newest episode available
        media_folder = Path(context.user_data['media_data']["path"])
        latest = max(self.function.episodes_present_in_folder(media_folder), default="S00E00")
        entry["last"] = latest

        # Save JSON
        async with aiofiles.open(self.data_json, "w") as f:
            await f.write(json.dumps(data, indent=4))

        title = context.user_data['media_data'].get("title", "")
        await self.function.send_message(f"✅ Je bent nu aangemeld voor nieuwe afleveringen van *{self.function.sanitize_text(title)}*.", update, context)
        await self.log.logger(f"*ℹ️ User has subscribed to the serie {self.function.sanitize_text(title)} - ({serie_id}) ℹ️*\nGebruiker: {context.user_data['gebruiker']}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")

        return ConversationHandler.END
