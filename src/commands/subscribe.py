#!/usr/bin/python3

import json
import asyncio
import aiofiles
from datetime import datetime
from typing import Union, Optional
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from src.services.sonarr import Sonarr
from src.commands.schedule import Schedule

from src.states import AFMELDEN_OPTIE, AANMELD_OPTIE, AANMELD_CHOICE


class Subscribe:

    def __init__(self, args, logger, functions):

        # Set default values
        self.log = logger
        self.function = functions
        self.sonarr = Sonarr(logger)
        self.schedule = Schedule(args, logger, self.function)

        # Set data.json/stats.json file based on live/dev arg
        self.data_json = "data.json" if args.env == "live" else "data.dev.json"
        self.stats_json = "stats.json" if args.env == "live" else "stats.dev.json"


    async def aanmelden(self, update: Update, context: CallbackContext) -> int:

        await self.function.send_message("Voor welke serie wil je aanmelden om updates te ontvangen van nieuwe afleveringen?",update, context)
        return AANMELD_OPTIE


    async def aanmeld_optie(self, update: Update, context: CallbackContext) -> int:

        # Sanatize and set response variable
        sanitize_message = self.function.sanitize_text(update.message.text)
        context.user_data["aanmeld_optie"] = sanitize_message

        # Send start message
        await self.function.send_message(f"Oke, je wilt je dus graag aanmelden voor *{sanitize_message}*. Even kijken of dat mogelijk is...", update, context)
        await asyncio.sleep(1)

        # Make the API request
        context.user_data["aanmeld_object"] = await self.sonarr.lookup_by_name(sanitize_message)

        # End conversation if no results are found
        if not context.user_data["aanmeld_object"]:
            await self.function.send_message(f"Er zijn geen resultaten gevonden voor de serie *{sanitize_message}*. Misschien heb je een typfout gemaakt in de titel? Stuur /aanmelden om het nogmaals te proberen.", update, context)
            return ConversationHandler.END

        # Get first max 10 items which are downløaden
        results = [
            (idx, item)
            for idx, item in enumerate(context.user_data["aanmeld_object"])
            if isinstance(item, dict) and item.get("path") and not item.get("ended", False)
        ][:10]

        # End conversation if no results are found
        if not results:
            await self.function.send_message(f"Er zijn geen resultaten gevonden voor de serie *{sanitize_message}*. Het kan zijn dat de serie nog niet gedownløad is of dat deze al is afgelopen. Stuur /aanmelden om het nogmaals te proberen.", update, context)
            return ConversationHandler.END

        await self.function.send_message(f"De volgende opties zijn gevonden met de term *{sanitize_message}*:", update, context)
        await asyncio.sleep(1)

        # Loop to all media hits
        for display_index, (orig_index, item) in enumerate(results, start=1):

            # Get the values with backup if non-existing
            title = item.get('title', sanitize_message)
            sanitize_title = self.function.sanitize_text(title)
            year = item.get('year', 'Jaartal onbekend')
            overview = item.get('overview', 'Geen beschrijving beschikbaar')
            sanitize_overview = self.function.sanitize_text(overview)
            remote_poster = item.get('remotePoster')

            # Send message based on remote_poster availability
            if remote_poster:
                await self.function.send_image(f"*Optie {display_index} - {sanitize_title} ({year})*\n\n{sanitize_overview}", remote_poster, update, context)
            else:
                await self.function.send_message(f"*Optie {display_index} - {sanitize_title} ({year})*\n\n{sanitize_overview}", update, context)

            # Sleep between msg's
            await asyncio.sleep(1)

        # create the keyboard with 2 per row
        buttons = [
            InlineKeyboardButton(f"Option {display_index}", callback_data=f"{orig_index}")
            for display_index, (orig_index, _) in enumerate(results, start=1)
        ]
        keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send the message with the keyboard options
        await self.function.send_message(f"Voor welke serie wil je graag updates ontvangen?\n\n_Mis je een serie uit de lijst? Dan is deze nog niet gedownløad of al afgelopen. Stuur /start om een downløad te starten, hierna krijg je de optie om je aan te melden voor updates._", update, context, reply_markup)

        # Return to the next state
        return AANMELD_CHOICE


    async def aanmeld_keus(self, update: Update, context: CallbackContext) -> int:

        # Answer query and set aanmeld_data based on option number
        await update.callback_query.answer()
        orig_index = int(update.callback_query.data)
        context.user_data['aanmeld_data'] = context.user_data["aanmeld_object"][orig_index]

        # Get tmdbId
        serie_id = str(context.user_data['aanmeld_data'].get("tmdbId"))
        if not serie_id or serie_id == "None":
            await self.function.send_message("Er ging iets fout bij het ophalen van data van de serie. De serverbeheerder is hiervan op de hoogte en zal dit zo snel mogelijk oplossen. Probeer het op een later moment nog is.", update, context)
            await self.log.logger(f"Error happened during parsing tmdbId in subscribe.py, see the logs for the media JSON.", False, "error", True)
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
        entry["started"] = False

        # Set to newest episode available
        media_folder = Path(context.user_data['aanmeld_data']["path"])
        latest = max(self.function.episodes_present_in_folder(media_folder), default="S00E00")
        entry["last"] = latest

        # Save JSON
        async with aiofiles.open(self.data_json, "w") as f:
            await f.write(json.dumps(data, indent=4))

        title = context.user_data['aanmeld_data'].get("title", "")
        await self.function.send_message(f"✅ Je bent nu aangemeld voor nieuwe afleveringen van *{self.function.sanitize_text(title)}*.", update, context)
        await self.log.logger(f"*ℹ️ User has subscribed to the serie {self.function.sanitize_text(title)} - ({serie_id}) ℹ️*\nGebruiker: {context.user_data['gebruiker']}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")

        return ConversationHandler.END


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
            media_json = self.first_item(await self.sonarr.lookup_by_tmdbid(serie_id))
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
        title = media_json.get("title") if media_json else f"Serie {serie_id}"

        await self.function.send_message(f"✅ Je bent nu afgemeld voor *{self.function.sanitize_text(title)}*",update, context)
        await self.log.logger(f"*ℹ️ User has ubsubscribed to the serie {self.function.sanitize_text(title)} - ({serie_id}) ℹ️*\nGebruiker: {context.user_data['gebruiker']}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")
        return ConversationHandler.END


    def first_item(self, obj):
        if not obj:
            return None
        if isinstance(obj, list):
            return obj[0] if obj else None
        return obj if isinstance(obj, dict) else None
