#!/usr/bin/python3

import asyncio
import os
import json
import traceback
import time
from datetime import datetime
from typing import Optional
from abc import ABC, abstractmethod
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext, ConversationHandler

from src.states import REQUEST_AGAIN, REQUEST_MOVIE, REQUEST_SERIE, AANMELDEN_SERIE
from src.services.plex import Plex
from src.services.transmission import TransmissionService, check_transmission_and_trigger_scans
from src.commands.start import Start
from src.log import get_logger


log = get_logger(__name__)

# The media type in a line, per label of the conversation
MEDIA_TYPES = {"film": "movie", "serie": "series"}


def title_and_year(media: dict) -> str:
    """ How a media item of Radarr or Sonarr reads in a line: its title, with the year when it has one """
    title = media.get("title") or f"tmdb {media.get('tmdbId')}"
    return f"{title} ({media['year']})" if media.get("year") else title


def results_text(n: int) -> str:
    """ The number of results of a search, as it reads in a line """
    return f"{n} result" if n == 1 else f"{n} results"


def chosen_media(user_data: dict) -> dict:
    """ The media item the user chose, as Radarr or Sonarr names it, for the lines of the steps after the choice.

    The title in media_data is sanitized for the answers. A Gesprek that started before media_item existed only
    has media_data.
    """
    return user_data.get("media_item") or user_data["media_data"]


class Media(ABC):
    """ Base class for media handling """

    def __init__(self, args, logger, functions, telegram, media_handler, label, media_folder, option_state):

        # Set default values
        self.args = args
        self.log = logger
        self.function = functions
        self.telegram = telegram
        self.media_handler = media_handler
        self.label = label
        self.media_folder = media_folder
        self.option_state = option_state
        self.plex = Plex(self.log)
        self.start = Start(self.args, self.log, self.function)

        # Set data.json/stats.json file based on live/dev arg
        self.data_json = "data.json" if args.env == "live" else "data.dev.json"
        self.stats_json = "stats.json" if args.env == "live" else "stats.dev.json"

    @abstractmethod
    async def get_media_states(self) -> dict:
        """ Abstract method that defines the states in the subclasses """
        pass

    @abstractmethod
    async def create_download_payload(self, media_data: dict, folder: str) -> dict:
        """ Abstract method that generates the download payload for Radarr/Sonarr """
        pass

    @abstractmethod
    async def media_upgrade(self, update: Update, context: CallbackContext) -> Optional[int]:
        """ Handles if the user wants the media to be quality upgraded """
        pass

    @abstractmethod
    async def media_upgrade_info(self, update: Update, context: CallbackContext) -> Optional[int]:
        """ Handles the specific info about the media upgrade """
        pass

    async def request_media(self, update: Update, context: CallbackContext) -> Optional[int]:
        """ Handles the parsing of the chosen media and gives the options for which one the user wants """

        # Create user data from global vars
        context.user_data['label'] = self.label
        context.user_data['media_folder'] = self.media_folder
        context.user_data['option_state'] = self.option_state

        # Sanatize and set response variable
        sanitize_message = self.function.sanitize_text(update.message.text)
        context.user_data["requested_media"] = sanitize_message

        # Send start message
        await self.function.send_message(f"Oke, je wilt dus graag {sanitize_message} op Plęx zien. Even kijken of dat mogelijk is...", update, context)
        await asyncio.sleep(1)

        # Make the API request
        context.user_data["media_object"] = await self.media_handler.lookup_by_name(sanitize_message)

        # The search term as the user typed it
        found = len(context.user_data["media_object"] or [])
        log.info(f"searched '{update.message.text}' for {MEDIA_TYPES[self.label]}: {results_text(found)}",
                 event="search_term", query=update.message.text, media_type=MEDIA_TYPES[self.label], results=found)

        # End or retry conversation if no results are found
        if not context.user_data["media_object"]:

            # Create keyboard
            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Ja", callback_data="yes"),
                    InlineKeyboardButton("Nee", callback_data="no")
                ]
            ])

            await self.function.send_message(f"Er zijn geen resultaten gevonden voor de {context.user_data['label']} {sanitize_message}. Misschien heb je een typfout gemaakt in de titel? Wil je het nogmaals proberen?", update, context, reply_markup)
            return REQUEST_AGAIN

        await self.function.send_message(f"De volgende {context.user_data['label']}s zijn gevonden met de term {sanitize_message}:", update, context)
        await asyncio.sleep(1)

        # Show the first 5 options
        return await self.send_media_options(update, context, 0)

    async def send_media_options(self, update: Update, context: CallbackContext, start: int) -> Optional[int]:
        """ Sends 5 media options starting at the given index, together with the options keyboard """

        # Remember how many options are shown, so 'toon meer' can only be used once
        end = start + 5
        context.user_data["options_shown"] = end

        # Loop to the media hits of this page
        for counter, item in enumerate(context.user_data["media_object"][start:end], start=start):

            # Get the values with backup if non-existing
            title = item.get('title', context.user_data["requested_media"])
            sanitize_title = self.function.sanitize_text(title)
            year = item.get('year', 'Jaartal onbekend')
            overview = item.get('overview', 'Geen beschrijving beschikbaar')
            sanitize_overview = self.function.sanitize_text(overview)
            remote_poster = item.get('remotePoster')
            if context.user_data['label'] == "serie":
                score = item.get('ratings', {}).get('value', 'Score onbekend')
            else:
                score = item.get('ratings', {}).get('imdb', {}).get('value', 'Score onbekend')

            # Send message based on remote_poster availability
            if remote_poster:
                await self.function.send_image(f"*Optie {counter + 1} - {sanitize_title} ({year})*\n*IMDB: {score} ⭐️*\n\n{sanitize_overview}", remote_poster, update, context)
            else:
                await self.function.send_message(f"*Optie {counter + 1} - {sanitize_title} ({year})*\n*IMDB: {score} ⭐️*\n\n{sanitize_overview}", update, context)

            await asyncio.sleep(1)

        # Create the options keyboard (2 options per row) for all shown options
        shown = range(min(end, len(context.user_data["media_object"])))
        keyboard = [
            [InlineKeyboardButton(f"Optie {i + 1}", callback_data=f"{i}") for i in shown[j:j + 2]]
            for j in range(0, len(shown), 2)
        ]

        # Only offer 'toon meer' on the first page and when there are more hits
        if start == 0 and len(context.user_data["media_object"]) > end:
            keyboard.append([InlineKeyboardButton("🔎 Toon meer", callback_data="more")])
        keyboard.append([InlineKeyboardButton("🔄 Probeer opnieuw", callback_data="retry")])

        # Send the message with the keyboard options
        await self.function.send_message(f"Welke optie wil je graag op Plęx zien?\n\n_Staat je keuze er niet tussen? Kies dan voor 'Probeer opnieuw' om een andere titel in te voeren_", update, context, InlineKeyboardMarkup(keyboard))

        # Return to the next state
        return context.user_data['option_state']

    async def media_show_more(self, update: Update, context: CallbackContext) -> Optional[int]:
        """ Shows the next 5 media options (only once) """

        # Answer query and remove the keyboard of the previous options message
        log.info("pressed 'show more'", event="search_button", button="more")
        await update.callback_query.answer()
        await update.callback_query.edit_message_reply_markup(reply_markup=None)

        # Ignore if 'toon meer' was already used
        if context.user_data.get("options_shown", 0) > 5:
            return context.user_data['option_state']

        return await self.send_media_options(update, context, 5)

    async def request_media_again(self, update: Update, context: CallbackContext):

        # 'Probeer opnieuw' under the options, or yes/no after a search without results
        button = update.callback_query.data
        log.info("pressed 'try again'" if button == "retry" else f"try again after no results: {button}",
                 event="search_button", button=button)

        # Acknowledge the callback
        await update.callback_query.answer()

        if update.callback_query.data == "no":
            await self.function.send_message(f"Oke, je kan de bot altijd opnieuw starten door /start te sturen.", update, context)
            return ConversationHandler.END

        # Remove the options keyboard when coming from the 'probeer opnieuw' button
        if update.callback_query.data == "retry":
            await update.callback_query.edit_message_reply_markup(reply_markup=None)

        # Try again based on the previously chosen media type
        media_type = context.user_data.get("media_type")

        # Clear previous attempt data (keep media_type so routing still works)
        context.user_data.pop("requested_media", None)
        context.user_data.pop("media_object", None)
        context.user_data.pop("media_data", None)
        context.user_data.pop("media_item", None)
        context.user_data.pop("options_shown", None)

        if media_type == "serie":
            await self.function.send_message("Welke serie wil je graag op Plęx zien?", update, context)
            return REQUEST_SERIE

        if media_type == "movie":
            await self.function.send_message("Welke film wil je graag op Plęx zien?", update, context)
            return REQUEST_MOVIE

        # Fallback: unknown state, end safely
        await self.function.send_message("Oeps, de bot weet niet meer of je een film of serie aan het aanvragen was. Stuur /start om opnieuw te beginnen.", update, context)
        return ConversationHandler.END

    async def media_option(self, update: Update, context: CallbackContext) -> Optional[int]:
        """ Handles the specific user media choice and downloads it """

        # Answer query and set media_data based on option number
        await update.callback_query.answer()
        option = int(update.callback_query.data) + 1
        context.user_data['media_data'] = context.user_data["media_object"][option - 1]

        # The media item as Radarr or Sonarr names it, for the lines of this and the next steps:
        # the title in media_data is sanitized for the answers below
        context.user_data['media_item'] = {key: context.user_data['media_data'].get(key) for key in ("title", "year", "tmdbId")}
        chosen = context.user_data['media_item']

        # Only the size check below may unmonitor this download, user_data is persisted between requests
        context.user_data.pop("set_monitored", None)

        # Check Transmission and fetch active torrents
        transmission = TransmissionService(self.log)
        transmission_up, active_torrents = await transmission.get_active_torrents()

        # Get the media states
        states = await self.get_media_states()

        # Loop through states
        for state, details in states.items():
            if details["condition"](context.user_data['media_data'], active_torrents):

                # Sanitize title and set a var
                context.user_data['media_data']['title'] = self.function.sanitize_text(context.user_data['media_data']['title'])

                # Do serie season size check if defined: a serie with more than 5 seasons is added unmonitored
                seasons = context.user_data['media_data']["statistics"]["seasonCount"] if "size_check" in details else 0
                too_many_seasons = seasons > 5
                if too_many_seasons:
                    await self.function.send_message(f"Je hebt een serie aangevraagd die meer dan 5 seizoenen heeft, omdat de server opslag beperkt is zal deze aanvraag handmatig beoordeeld worden. Er bestaat een reële kans dat de serie hierdoor niet gedownløad zal worden.\n\nWil je de serie echt super graag op Plęx zien? Stuur dan een bericht door /help te sturen en te kiezen voor de optie: *📍 Anders*", update, context)
                    await asyncio.sleep(1)
                    context.user_data["set_monitored"] = False

                # Do actions if defined
                failed = "action" in details and not await getattr(self, details["action"])(update, context)

                # What the bot found. While Transmission is down, the user hears there is no room to start the download.
                if failed:
                    outcome = "failed"
                elif too_many_seasons:
                    outcome = "unmonitored"
                elif not transmission_up and details.get("action") == "start_download":
                    outcome = "no_space"
                else:
                    outcome = details["outcome"]
                found = outcome.replace("_", " ") + (f", {seasons} seasons" if too_many_seasons else "")
                log.info(f"chose option {option}: {title_and_year(chosen)}: {found}", event="media_request",
                         option=option, media_type=MEDIA_TYPES[self.label], outcome=outcome,
                         seasons=seasons if too_many_seasons else None, media=chosen)

                # user was informerd in previous steps about the error
                if failed:
                    return ConversationHandler.END

                if too_many_seasons:

                    # Send the notify message
                    await self.ask_notify_question(update, context, "notify", f"Wil je een melding ontvangen als {context.user_data['media_data']['title']} online staat?")

                    # Tell the Beheerder, who decides whether it is downloaded
                    await self.telegram.send_admin_message(f"*⚠️ User has requested {context.user_data['media_data']['title']} ({context.user_data['media_data']['tmdbId']}) with {seasons} seasons ⚠️*\nGebruiker: {context.user_data['gebruiker']}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}",
                                                           f"request of a series with {seasons} seasons")

                    # Write to stats file
                    await self.write_to_stats(update, context)

                    # Return to next state
                    return details["next_state"]

                # Do extra action if defined
                if "extra_action" in details:
                    await getattr(self.media_handler, details["extra_action"])()

                # Inform owner about unmonitored series if defined
                if "inform_unmonitored" in details:
                    await self.telegram.send_admin_message(f"*ℹ️ User has requested {context.user_data['media_data']['title']} which has been marked as unmonitored ℹ️*\nGebruiker verwacht reactie of het wel/niet gedownload gaat worden.\nGebruiker: {context.user_data['gebruiker']}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}",
                                                           f"request of an unmonitored {MEDIA_TYPES[self.label]}")

                # Send the message if defined
                if "message" in details:
                    # Adjust wording so we don't promise an immediate download start if transmission is down.
                    msg = details["message"].format(title=context.user_data['media_data']['title'])
                    if outcome == "no_space":
                        msg = (
                            f"Er is op dit moment helaas te weinig ruimte op de server om de downløad te starten. "
                            f"Dit probleem is tijdelijk, er is al een nieuwe harde schijf besteld.\n\n "
                            f"*{context.user_data['media_data']['title']}* zal daarom later gedownløad worden."
                        )
                    await self.function.send_message(msg, update, context)
                    await asyncio.sleep(1)

                # Only if media is already downloaded
                if state == "already_downloaded":

                    # Get the Plęx url of the media
                    media_plex_url = await self.plex.get_media_url(context.user_data['media_data'], context.user_data['label'])
                    if not media_plex_url:
                        await self.function.send_message(f"Zo te zien is {context.user_data['media_data']['title']} al gedownløad.", update, context)
                    else:
                        await self.function.send_message(f"Zo te zien is {context.user_data['media_data']['title']} al gedownløad.\n\n🌐 <a href='{media_plex_url}'>Bekijk {context.user_data['media_data']['title']} in de browser</a>", update, context, None, "HTML")

                    # Send the notify message
                    await asyncio.sleep(1)
                    if context.user_data['label'] == "serie":
                        await self.ask_notify_question(update, context, "upgrade", f"Heb je {context.user_data['media_data']['title']} aangevraagd omdat er iets mis is met de downløad? Bijvoorbeeld: \n- Slechte (720p) kwaliteit\n- Reclame in het scherm\n- Chinese ondertiteling\n- Missende episode(s)")
                    else:
                        await self.ask_notify_question(update, context, "upgrade", f"Heb je {context.user_data['media_data']['title']} aangevraagd omdat er iets mis is met de downløad? Bijvoorbeeld: \n- Slechte (720p) kwaliteit\n- Reclame in het scherm\n- Chinese ondertiteling\n- Audio klopt niet")

                    # Write to stats file
                    await self.write_to_stats(update, context)

                    # Tell the Beheerder
                    await self.telegram.send_admin_message(f"*ℹ️ User has requested {context.user_data['media_data']['title']} - ({context.user_data['media_data']['tmdbId']}) while it's already downløaded ℹ️*\nGebruiker: {context.user_data['gebruiker']}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}",
                                                           f"request of a downloaded {MEDIA_TYPES[self.label]}")

                    # Return the next specific state
                    return details["next_state"]

                # Send the question message for the next state
                if "state_message" in details:

                    # Send the notify message
                    await self.ask_notify_question(update, context, "notify", f"Wil je een melding ontvangen als {context.user_data['media_data']['title']} online staat?")

                # Tell the Beheerder (films: include release year next to title when Radarr provides it)
                md = context.user_data["media_data"]
                title_for_log = md.get("title") or "Unknown title"
                if context.user_data["label"] == "film":
                    movie_year = md.get("year")
                    if movie_year:
                        title_for_log = f"{title_for_log} ({movie_year})"

                await self.telegram.send_admin_message(
                    f"*ℹ️ User has requested the {context.user_data['label']} {title_for_log} - ({md.get('tmdbId', 'unknown')}) ℹ️*\n"
                    f"Gebruiker: {context.user_data['gebruiker']}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}",
                    f"{MEDIA_TYPES[self.label]} requested",
                )

                # Write to stats file
                await self.write_to_stats(update, context)

                # Check if Transmission recovered and kick missing-media scans if so.
                try:
                    await check_transmission_and_trigger_scans(
                        logger=self.log,
                        radarr=self.media_handler if context.user_data.get("label") == "film" else None,
                        sonarr=self.media_handler if context.user_data.get("label") == "serie" else None,
                    )
                except Exception:
                    # Never fail the user flow because of a health check.
                    pass

                # Return the next specific state
                return details["next_state"]

        # Fallback error: if no state matches
        log.info(f"chose option {option}: {title_and_year(chosen)}: failed", event="media_request", option=option,
                 media_type=MEDIA_TYPES[self.label], outcome="failed", media=chosen)
        await self.function.send_message(f"*😵 Oeps, daar ging iets fout*\n\nDe serverbeheerder is op de hoogte gesteld van het probleem, je kan het nog een keer proberen in de hoop dat het dan wel werkt, of je kan het op een later moment nogmaals proberen.", update, context)
        await self.log.logger(f"Error happened during media state filtering, see the logs for the media JSON.", False, "error", True)
        await self.log.logger(f"Media JSON:\n{context.user_data['media_data']}", False, "error", False)
        return ConversationHandler.END

    async def ask_notify_question(self, update: Update, context: CallbackContext, type: str, msg: str) -> None:
        """ Asks if the user want to stay notified about the download """

        # Create the keyboard
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Ja", callback_data=f"{context.user_data['label']}_{type}_yes"),
                InlineKeyboardButton("Nee", callback_data=f"{context.user_data['label']}_{type}_no")
            ]
        ])

        # Send the notify message
        await self.function.send_message(msg, update, context, reply_markup)

    async def stay_notified(self, update: Update, context: CallbackContext) -> Optional[int]:
        """ Handles if the user wants te be updated about the requested media """

        # Answer query
        await update.callback_query.answer()
        choice = "no" if update.callback_query.data == f"{context.user_data['label']}_notify_no" else "yes"
        media = chosen_media(context.user_data)
        log.info(f"notify when {title_and_year(media)} is online: {choice}", event="notify_choice", choice=choice,
                 media=media)

        # Finish conversation if chosen
        if choice == "no":
            await self.function.send_message(f"Oke, bedankt voor het gebruiken van deze bot. Wil je nog iets anders downløaden? Stuur dan /start", update, context)
            return ConversationHandler.END

        # Add media_id + user_id to JSON
        with open(self.data_json, "r+") as file:
            json_data = json.load(file)

            # Check if user already has entry in the notify list, otherwise create it
            if str(update.effective_user.id) not in json_data["notify_list"]:
                json_data["notify_list"][f"{update.effective_user.id}"] = {}

            # Check if serie/film block exists, otherwise create it
            for media_type in ["serie", "film", "recurring_serie"]:
                if media_type not in json_data["notify_list"][f"{update.effective_user.id}"]:
                    json_data["notify_list"][f"{update.effective_user.id}"][f"{media_type}"] = {}

            # Add media to notify_list
            json_data["notify_list"][f"{update.effective_user.id}"][f"{context.user_data['label']}"][context.user_data['media_data']["tmdbId"]] = round(time.time())

            # Write to the file
            file.seek(0)
            json.dump(json_data, file, indent=4)
            file.truncate()

        # Send final message
        if context.user_data['label'] == "serie" and not context.user_data['media_data'].get("ended", False):
            await self.function.send_message(f"Oke, je ontvangt een melding als {context.user_data['media_data']['title']} beschikbaar is.", update, context)
            await asyncio.sleep(1)

            # Create keyboard
            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Ja", callback_data="yes"),
                    InlineKeyboardButton("Nee", callback_data="no")
                ]
            ])
            await self.function.send_message(f"Wil je ook updates ontvangen zodra er nieuwe afleveringen online komen? Je kan je hiervoor later altijd afmelden door /afmelden te sturen.", update, context, reply_markup)
            return AANMELDEN_SERIE
        else:
            await self.function.send_message(f"Oke, je ontvangt een melding als {context.user_data['media_data']['title']} beschikbaar is. Wil je nog iets anders downløaden? Stuur dan /start", update, context)
            return ConversationHandler.END


    async def start_download(self, update: Update, context: CallbackContext) -> bool:
        """ Starts the download in Radarr or Sonarr """

        # Get folder to download to
        download_folder = await self.check_disk_space(context)

        # Check if enough space is left
        if not download_folder:
            await self.function.send_message(f"*😵 Er is op dit moment een probleem met de opslag van de Plęx server*\n\nDe serverbeheerder is hiervan op de hoogte en zal dit zo snel mogelijk oplossen. Probeer het op een later moment nog is.", update, context)
            await self.log.logger(f"Error happened during the check of the diskspace", False, "error", True)
            return False

        # Create the download payload
        set_monitored = context.user_data.get("set_monitored", True)
        payload = await self.create_download_payload(context.user_data['media_data'], download_folder, set_monitored)

        # Check if payload creation was succesfull
        if not payload:
            await self.function.send_message(f"Er ging iets mis bij het starten van de downløad. De serverbeheerder is hiervan op de hoogte en zal dit zo snel mogelijk oplossen. Probeer het op een later moment nog is.", update, context)
            return False

        # Queue download
        response = await self.media_handler.queue_download(payload)

        # Check if download queue was succesfull
        if not response:
            await self.function.send_message(f"Er ging iets mis bij het starten van de downløad. De serverbeheerder is hiervan op de hoogte en zal dit zo snel mogelijk oplossen. Probeer het op een later moment nog is.", update, context)
            return False

        return True

    async def check_disk_space(self, context: CallbackContext) -> Optional[str]:
        """Checks if any configured media folder has >= 150GB free on its mount."""

        # Get list of disks and diskspace
        disk_list = [p.strip() for p in context.user_data["media_folder"].split(",") if p.strip()]
        disk_space = await self.media_handler.get_disk_space()

        # Check retrieve diskspace succesfull
        if not disk_space:
            await self.log.logger("No disk space data returned", False, "error", True)
            return None

        # 150GB to bytes
        GB_150 = 150 * 1024 ** 3

        # Pre-normalize mount paths
        mounts = []
        for d in disk_space:
            mount = os.path.normpath(d["path"])
            mounts.append({**d, "path": mount})

        def is_under(folder: str, mount: str) -> bool:
            folder = os.path.normpath(folder)
            mount = os.path.normpath(mount)
            return folder == mount or folder.startswith(mount + os.sep)

        for folder in disk_list:
            folder_norm = os.path.normpath(folder)

            # find best (most specific) mount for this folder
            candidates = [d for d in mounts if is_under(folder_norm, d["path"])]
            if not candidates:
                continue

            best = max(candidates, key=lambda d: len(d["path"]))

            if best.get("freeSpace", 0) > GB_150:
                # return the folder you want to use (the configured one)
                return folder_norm

        return None

    async def write_to_stats(self, update: Update, context: CallbackContext) -> None:
        """ Writes stats to the stats.json file """

        # Add media download requests to the stats
        try:
            with open(self.stats_json, "r+") as file:
                data = json.load(file)
                data[f"{update.effective_user.id}"][f"{context.user_data['label']}_requests"][datetime.now().strftime("%d-%m-%Y %H:%M:%S")] = context.user_data['media_data']['title']
                file.seek(0)
                json.dump(data, file, indent=4)
                file.truncate()
        except Exception as e:
            await self.log.logger(f"Error during write to stats.json for media {context.user_data['media_data']['title']} and user {context.user_data['gebruiker']}, username {update.effective_user.first_name}.\n\nError: {' '.join(e.args)}\nTraceback:\n{traceback.format_exc()}", False, "error", True)
