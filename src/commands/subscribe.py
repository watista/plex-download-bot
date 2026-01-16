#!/usr/bin/python3

import json
import asyncio
import aiofiles
from datetime import datetime
from typing import Union, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from src.services.sonarr import Sonarr

from src.states import AFMELDEN_OPTIE


class Subscribe:

    def __init__(self, args, logger, functions):

        # Set default values
        self.log = logger
        self.function = functions
        self.sonarr = Sonarr(logger)

        # Set data.json/stats.json file based on live/dev arg
        self.data_json = "data.json" if args.env == "live" else "data.dev.json"
        self.stats_json = "stats.json" if args.env == "live" else "stats.dev.json"


    async def aanmelden(self, update: Update, context: CallbackContext) -> int:
        print(123)


    async def afmelden(self, update: Update, context: CallbackContext) -> int:
        user_id = str(update.effective_user.id)

        # Load JSON file
        async with aiofiles.open(self.data_json, "r") as file:
            data = json.loads(await file.read())

        serie_episode = (
            data.get("notify_list", {})
                .get(user_id, {})
                .get("serie_episode", {})
        )

        if not serie_episode:
            await self.function.send_message("Je bent niet aangemeld voor serie updates, dus er is ook niks om voor af te melden. 😀",update, context)
            return ConversationHandler.END

        # Build buttons
        buttons = []
        for serie_id, state in serie_episode.items():
            print(serie_id)
            media_json = self.first_item(await self.sonarr.lookup_by_tmdbid(serie_id))
            print(media_json)
            title = media_json.get("title") if media_json else f"Serie {serie_id}"

            # Callback data must be <= 64 bytes => keep it short
            buttons.append(
                InlineKeyboardButton(f"{title}", callback_data=f"{serie_id}")
            )

        reply_markup = InlineKeyboardMarkup([[b] for b in buttons])

        await self.function.send_message("Voor welke serie wil je afmelden?", update, context, reply_markup)

        return AFMELDEN_OPTIE


    async def afmelden_optie(self, update: Update, context: CallbackContext) -> None:

        query = update.callback_query
        await query.answer()

        serie_id = query.data
        user_id = str(query.from_user.id)
        print(serie_id)

        # Load JSON
        async with aiofiles.open(self.data_json, "r") as file:
            data = json.loads(await file.read())

        user_node = data.setdefault("notify_list", {}).setdefault(user_id, {})
        serie_episode = user_node.setdefault("serie_episode", {})

        # Remove serie from list
        serie_episode.pop(serie_id, None)

        # Save JSON
        async with aiofiles.open(self.data_json, "w") as file:
            await file.write(json.dumps(data, indent=4))

        # show title
        media_json = self.first_item(await self.sonarr.lookup_by_tmdbid(serie_id))
        print(media_json)
        title = media_json.get("title") if media_json else f"Serie {serie_id}"

        await self.function.send_message(f"✅ Je bent nu afgemeld voor *{title}*",update, context)
        return ConversationHandler.END


    def first_item(self, obj):
        if not obj:
            return None
        if isinstance(obj, list):
            return obj[0] if obj else None
        return obj if isinstance(obj, dict) else None
