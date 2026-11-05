#!/usr/bin/python3

import json
import asyncio
import aiofiles
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from src.services.sonarr import Sonarr
from src.commands.media import results_text, title_and_year
from src.conversation import ignored_line
from src.faults import Fault, FaultKind
from src.log import get_logger

from src.states import AFMELDEN_OPTIE, AANMELD_OPTIE, AANMELD_CHOICE, step_name


log = get_logger(__name__)


class Subscribe:

    def __init__(self, args, functions, telegram, faults):

        # Set default values
        self.function = functions
        self.telegram = telegram
        self.faults = faults
        self.sonarr = Sonarr(faults)

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

        # Get first max 10 items which are downløaden
        found = context.user_data["aanmeld_object"] or []
        options = [
            (idx, item)
            for idx, item in enumerate(found)
            if isinstance(item, dict) and item.get("path") and not item.get("ended", False)
        ][:10]

        # The search term as the user typed it, with the series that can be chosen
        in_sonarr = f" ({len(found)} found in Sonarr)" if len(found) != len(options) else ""
        log.info(f"searched '{update.message.text}' for series updates: {results_text(len(options))}{in_sonarr}",
                 event="search_term", query=update.message.text, media_type="series", purpose="series_updates",
                 results=len(options))

        # End conversation if no results are found
        if not found:
            await self.function.send_message(f"Er zijn geen resultaten gevonden voor de serie *{sanitize_message}*. Misschien heb je een typfout gemaakt in de titel? Stuur /start om het nogmaals te proberen.", update, context)
            return ConversationHandler.END

        # End conversation if no results are found
        if not options:
            await self.function.send_message(f"Er zijn geen resultaten gevonden voor de serie *{sanitize_message}*. Het kan zijn dat de serie nog niet gedownløad is of dat deze al is afgelopen. Stuur /start om het nogmaals te proberen.", update, context)
            return ConversationHandler.END

        await self.function.send_message(f"De volgende opties zijn gevonden met de term *{sanitize_message}*:", update, context)
        await asyncio.sleep(1)

        # Loop to all media hits
        for display_index, (orig_index, item) in enumerate(options, start=1):

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
            for display_index, (orig_index, _) in enumerate(options, start=1)
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
        aanmeld_data = context.user_data['aanmeld_data']
        serie_id = str(aanmeld_data.get("tmdbId"))
        if not serie_id or serie_id == "None":
            raise Fault.bug(what="The series has no tmdbId", details={"tmdbId": aanmeld_data.get("tmdbId")},
                            media={key: aanmeld_data.get(key) for key in ("title", "year", "tvdbId")})

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

        log.info(f"subscribed to new episodes of {title_and_year(context.user_data['aanmeld_data'])}",
                 event="series_updates", outcome="subscribed", media=context.user_data['aanmeld_data'])

        title = context.user_data['aanmeld_data'].get("title", "")
        await self.function.send_message(f"✅ Je bent nu aangemeld voor nieuwe afleveringen van *{self.function.sanitize_text(title)}*.", update, context)
        await self.telegram.send_admin_message(f"*ℹ️ User has subscribed to the serie {self.function.sanitize_text(title)} - ({serie_id}) ℹ️*\nGebruiker: {context.user_data['gebruiker']}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}",
                                               "series subscribed")

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
            log.info("nothing to unsubscribe from", event="series_updates", outcome="nothing_to_unsubscribe")
            await self.function.send_message("Je bent niet aangemeld voor serie updates, dus er is ook niks om voor af te melden. 😀",update, context)
            return ConversationHandler.END

        # Build buttons
        buttons = []
        series = await self.series_in_sonarr(list(serie_episode))
        for serie_id, state in serie_episode.items():
            media_json = series.get(serie_id)
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

        # Only a serie from the list is a TMDB ID, a button of an older message (like option 1
        # of an earlier search) is not. Wait for a choice from the list.
        if serie_id not in serie_episode:
            log.info(**ignored_line(update, step_name(AFMELDEN_OPTIE)))
            await self.function.send_message("Deze knop hoort niet bij de lijst met series waarvoor je bent aangemeld. Kies een serie uit de lijst, of stuur /stop om te stoppen.", update, context)
            return AFMELDEN_OPTIE

        # Remove serie from list
        serie_episode.pop(serie_id, None)

        # Save JSON
        async with aiofiles.open(self.data_json, "w") as file:
            await file.write(json.dumps(data, indent=4))

        # show title
        media_json = (await self.series_in_sonarr([serie_id])).get(serie_id)
        title = media_json.get("title") if media_json else f"Serie {serie_id}"

        media = media_json or {"tmdbId": int(serie_id)}
        log.info(f"unsubscribed from new episodes of {title_and_year(media)}", event="series_updates",
                 outcome="unsubscribed", media=media)

        await self.function.send_message(f"✅ Je bent nu afgemeld voor serie updates van *{self.function.sanitize_text(title)}*",update, context)
        await self.telegram.send_admin_message(f"*ℹ️ User has ubsubscribed to the serie {self.function.sanitize_text(title)} - ({serie_id}) ℹ️*\nGebruiker: {context.user_data['gebruiker']}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}",
                                               "series unsubscribed")
        return ConversationHandler.END


    async def series_in_sonarr(self, serie_ids: list[str]) -> dict[str, dict]:
        """ The series in Sonarr per TMDB ID, only for their titles: the user sees the TMDB ID of one that is missing.

        A Fout is reported, and the bot goes on. After a Storing it does not look up the other series: one failed
        attempt is enough, and each would wait for its own attempts.
        """
        series = {}
        for serie_id in serie_ids:
            try:
                series[serie_id] = await self.sonarr.lookup_by_tmdbid(serie_id)
            except Fault as fault:
                await self.faults.report(fault, continued="went on with the TMDB ID instead of the title")
                if fault.kind == FaultKind.DISRUPTION:
                    break
        return series
