#!/usr/bin/python3

import os
import re
import json
import aiofiles
from pathlib import Path
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from src.states import SERIE_OPTION, SERIE_NOTIFY, SERIE_UPGRADE, SERIE_UPGRADE_OPTION, SERIE_UPGRADE_INFO, AANMELDEN_SERIE
from src.commands.media import Media, chosen_media, title_and_year
from src.faults import Fault
from src.services.sonarr import Sonarr
from src.log import get_logger


log = get_logger(__name__)


class Serie(Media):
    """ Specific class for serie handling """

    filter_fields = ("path", "monitored", "status")

    def __init__(self, args, functions, telegram, faults):
        super().__init__(args, functions, telegram, faults, Sonarr(faults),
                         "serie", os.getenv('SERIE_FOLDERS'), SERIE_OPTION)

    async def get_media_states(self) -> dict:
        """ Function that defines the states """

        return {
            "downloading": {
                "outcome": "downloading",
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
                "outcome": "not_released",
                "condition": lambda serie, _: not serie.get("path") and serie.get("status") == "upcoming",
                "size_check": True,
                "message": "Op dit moment is {title} nog niet downløadbaar, hij is toegevoegd aan de te-downløaden-lijst. Zodra {title} gedownløad kan worden gebeurt dit automatisch.",
                "action": "start_download",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "not_available_already_requested": {
                "outcome": "not_released",
                "condition": lambda serie, _: serie.get("path") and serie.get("status") == "upcoming",
                "message": "Op dit moment is {title} nog niet downløadbaar, hij is toegevoegd aan de te-downløaden-lijst. Zodra {title} gedownløad kan worden gebeurt dit automatisch.",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "available_to_downl0ad": {
                "outcome": "download_started",
                "condition": lambda serie, _: not serie.get("path") and serie.get("status") != "upcoming",
                "size_check": True,
                "message": "De downløad voor {title} is nu gestart, gemiddeld duurt het 1 uur voordat een serie online staat, nog even geduld 😄",
                "action": "start_download",
                "extra_action": "scan_missing_media",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "unmonitored": {
                "outcome": "unmonitored",
                "condition": lambda serie, _: not serie.get("monitored"),
                "message": "{title} staat op dit moment aangemerkt als 'niet downløaden', dit kan verschillende redenen hebben. De serverbeheerder is op de hoogte gesteld van de aanvraag en zal deze beoordelen en er bij je op terug komen.",
                "inform_unmonitored": True,
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "already_downloaded": {
                "outcome": "already_downloaded",
                "condition": lambda serie, _: serie.get("path"),
                "next_state": SERIE_UPGRADE
            }
        }

    async def create_download_payload(self, data: dict, folder: str, monitor: bool) -> dict:
        """ Generates the download payload for Sonarr; a missing field falls through to the wrapper as a Bug """

        payload = {
            "title": data["title"],
            "qualityProfileId": 7,
            "monitored": monitor,
            "tvdbId": data["tvdbId"],
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
        choice = "no" if update.callback_query.data == "serie_upgrade_no" else "yes"
        log.info(f"something wrong with the download of {title_and_year(chosen_media(context.user_data))}: {choice}",
                 event="quality_request", choice=choice, media=chosen_media(context.user_data))

        # Finish conversation if chosen
        if choice == "no":
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
        reason = update.callback_query.data
        context.user_data["serie_upgrade_option"] = reason
        log.info(f"quality request for {title_and_year(chosen_media(context.user_data))}: {reason}",
                 event="quality_request", reason=reason, media=chosen_media(context.user_data))
        await update.callback_query.answer()

        # Aks question which season/episode needs to be upgrade
        await self.function.send_message(f"Om welk seizoen en/of episode gaat het?", update, context)
        return SERIE_UPGRADE_OPTION

    async def media_upgrade_option(self, update: Update, context: CallbackContext) -> None:
        """ Handles the answer for which season/episode the serie should be upgraded """

        # The season and episode as the user typed them
        text = update.message.text
        reason = context.user_data['serie_upgrade_option']
        log.info(f"quality request for {title_and_year(chosen_media(context.user_data))}: {reason}: '{text}'",
                 event="quality_request", reason=reason, text=text, media=chosen_media(context.user_data))

        # Send the confirmation message and notify option
        await self.telegram.send_admin_message(f"*⚠️ User did a quality request for {context.user_data['media_data']['title']} ({context.user_data['media_data']['tmdbId']}) ⚠️*\nSeason/Episode: {self.function.sanitize_text(text)}\nReason: {reason}\nGebruiker: {context.user_data['gebruiker']}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}",
                                               "quality request for a series")
        await self.function.send_message(f"Duidelijk! De aangegeven seizoenen/episodes worden zo snel mogelijk gefixt. Je ontvangt een bericht zodra dit is gedaan.", update, context)
        context.user_data.pop("serie_upgrade_option", None)
        return ConversationHandler.END


    async def aanmelden(self, update: Update, context: CallbackContext) -> None:
        """ Handles if the user wants te be updated about future new serie episodes """

        # Answer query
        await update.callback_query.answer()

        # Finish conversation if chosen
        if update.callback_query.data == "no":
            log.info(f"new episodes of {title_and_year(chosen_media(context.user_data))}: no", event="series_updates",
                     choice="no", media=chosen_media(context.user_data))
            await self.function.send_message(f"Oke, bedankt voor het gebruiken van deze bot. Wil je nog iets anders downløaden? Stuur dan /start", update, context)
            return ConversationHandler.END

        # Get tmdbId
        serie_id = str(context.user_data['media_data'].get("tmdbId"))
        if not serie_id or serie_id == "None":
            raise Fault.bug(what="The series has no tmdbId", details={"tmdbId": context.user_data['media_data'].get("tmdbId")},
                            media=chosen_media(context.user_data))

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
        entry["started"] = False

        # Set to the newest episode available. A new series has the path from the answer of Sonarr to its request
        # (start_download), so without one Sonarr does not have it right: the user is subscribed from the start on.
        media, tmdb_id = chosen_media(context.user_data), context.user_data['media_data']["tmdbId"]
        path = context.user_data['media_data'].get("path")
        if path:
            await self.faults.fixed("sonarr", "series_path", tmdb_id,
                                    msg=f"{media.get('title')} now has a path in Sonarr")
            entry["last"] = max(self.function.episodes_present_in_folder(Path(path)), default="S00E00")
        else:
            entry["last"] = "S00E00"
            await self.faults.report(Fault.setup(service="sonarr", what=f"{media.get('title')} has no path in Sonarr",
                                                 check="series_path", item=tmdb_id, media=media),
                                     continued="subscribed from the first episode on")

        # Save JSON
        async with aiofiles.open(self.data_json, "w") as f:
            await f.write(json.dumps(data, indent=4))

        log.info(f"new episodes of {title_and_year(chosen_media(context.user_data))}: yes: subscribed",
                 event="series_updates", choice="yes", outcome="subscribed", media=chosen_media(context.user_data))

        title = context.user_data['media_data'].get("title", "")
        await self.function.send_message(f"✅ Je bent nu aangemeld voor nieuwe afleveringen van *{self.function.sanitize_text(title)}*.", update, context)
        await self.telegram.send_admin_message(f"*ℹ️ User has subscribed to the serie {self.function.sanitize_text(title)} - ({serie_id}) ℹ️*\nGebruiker: {context.user_data['gebruiker']}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}",
                                               "series subscribed")

        return ConversationHandler.END
