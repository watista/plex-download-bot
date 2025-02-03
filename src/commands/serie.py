#!/usr/bin/python3

import asyncio
import os
import json
from transmission_rpc import Client

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext, ConversationHandler

from src.states import SERIE_OPTION, SERIE_NOTIFY
from src.commands.media import Media
from src.services.sonarr import Sonarr


class Serie(Media):
    """ Specific class for serie handling """

    def __init__(self, args, logger, functions):
        super().__init__(args, logger, functions, Sonarr(logger), "serie", os.getenv('SERIE_FOLDERS'), SERIE_OPTION)


    async def get_media_states(self):
        """ Function that defines the states """

        return {
            "downloading": {
                "condition": lambda serie, torrents: any(serie["title"].lower() in t.name.lower() for t in torrents),
                "message": "{title} wordt op dit moment al gedownload, nog even geduld 😄",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "not_available": {
                "condition": lambda serie, _: serie.get("serieFileId") == 0 and not serie.get("monitored") and serie.get("status") != "released",
                "message": "Op dit moment is {title} nog niet downloadbaar, hij is toegevoegd aan de te-downloaden-lijst. Zodra {title} gedownload kan worden gebeurt dit automatisch.",
                "action": "start_download",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "not_available": {
                "condition": lambda serie, _: serie.get("serieFileId") == 0 and serie.get("monitored") and serie.get("status") != "released",
                "message": "Op dit moment is {title} nog niet downloadbaar, hij is toegevoegd aan de te-downloaden-lijst. Zodra {title} gedownload kan worden gebeurt dit automatisch.",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "available_to_download": {
                "condition": lambda serie, _: serie.get("serieFileId") == 0 and not serie.get("monitored") and serie.get("status") == "released",
                "message": "De download voor {title} is nu gestart, het kan even duren voordat deze online staat, nog even geduld 😄",
                "action": "start_download",
                "extra_action": "scan_missing_media",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "available_to_download_but": {
                "condition": lambda serie, _: serie.get("serieFileId") == 0 and serie.get("monitored") and serie.get("status") == "released",
                "message": "Zo te zien is {title} wel al downloadbaar, alleen is er al een tijdje geen download-match gevonden. Misschien wordt er nog een download-match gevonden maar het kan ook zijn dat dit nog lang gaat duren of helemaal niet meer. Wil je deze serie echt super graag, dan kan je contact opnemen met de serverbeheerder om te kijken of de serie toch handmatig gedownload kan worden.",
                "state_message": True,
                "next_state": SERIE_NOTIFY
            },
            "already_downloaded": {
                "condition": lambda serie, _: serie.get("serieFileId") != 0 and serie.get("monitored"),
                "message": "{title} is al gedownload en staat online op Plex.",
                "next_state": ConversationHandler.END
            },
        }
