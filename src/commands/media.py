#!/usr/bin/python3

import asyncio
import os
import json
import traceback
import time
from datetime import datetime
from transmission_rpc import Client
from typing import Optional
from abc import ABC, abstractmethod
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext, ConversationHandler

from src.states import REQUEST_AGAIN
from src.services.plex import Plex
from src.commands.start import Start


class Media(ABC):
    """ Base class for media handling """

    def __init__(self, args, logger, functions, media_handler, label, media_folder, option_state):

        # Set default values
        self.args = args
        self.log = logger
        self.function = functions
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
        context.user_data["media_handler"] = self.media_handler
        context.user_data["label"] = self.label
        context.user_data["media_folder"] = self.media_folder
        context.user_data["option_state"] = self.option_state

        # Sanatize and set response variable
        sanitize_message = self.function.sanitize_text(update.message.text)
        context.user_data["requested_media"] = sanitize_message

        # Send start message
        await self.function.send_message(f"Oke, je wilt dus graag {sanitize_message} op Plęx zien. Even kijken of dat mogelijk is...", update, context)
        await asyncio.sleep(1)

        # Make the API request
        context.user_data["media_object"] = await context.user_data["media_handler"].lookup_by_name(sanitize_message)

        # End or retry conversation if no results are found
        if not context.user_data["media_object"]:

            # Create keyboard
            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Ja", callback_data="yes"),
                    InlineKeyboardButton("Nee", callback_data="no")
                ]
            ])

            await self.function.send_message(f"Er zijn geen resultaten gevonden voor de {context.user_data["label"]} {sanitize_message}. Misschien heb je een typfout gemaakt in de titel? Wil je het nogmaals proberen?", update, context, reply_markup)
            return REQUEST_AGAIN

        await self.function.send_message(f"De volgende {context.user_data["label"]}s zijn gevonden met de term {sanitize_message}:", update, context)
        await asyncio.sleep(1)

        # Set counter
        counter = 0

        # Loop to all media hits with a max of 5
        for item in context.user_data["media_object"][:5]:

            # Get the values with backup if non-existing
            title = item.get('title', sanitize_message)
            sanitize_title = self.function.sanitize_text(title)
            year = item.get('year', 'Jaartal onbekend')
            overview = item.get('overview', 'Geen beschrijving beschikbaar')
            sanitize_overview = self.function.sanitize_text(overview)
            remote_poster = item.get('remotePoster')

            # Send message based on remote_poster availability
            if remote_poster:
                await self.function.send_image(f"*Optie {counter + 1} - {sanitize_title} ({year})*\n\n{sanitize_overview}", remote_poster, update, context)
            else:
                await self.function.send_message(f"*Optie {counter + 1} - {sanitize_title} ({year})*\n\n{sanitize_overview}", update, context)

            # Bump counter
            counter += 1
            await asyncio.sleep(1)

        # Create the options keyboard
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"Optie {i + 1}", callback_data=f"{i}")
                for i in range(len(context.user_data["media_object"][:2]))
            ],
            [
                InlineKeyboardButton(f"Optie {i + 3}", callback_data=f"{i + 2}")
                for i in range(len(context.user_data["media_object"][2:4]))
            ],
            [
                InlineKeyboardButton(f"Optie {i + 5}", callback_data=f"{i + 4}")
                for i in range(len(context.user_data["media_object"][4:5]))
            ]
        ])

        # Send the message with the keyboard options
        await self.function.send_message(f"Welke optie wil je graag op Plęx zien?\n\n_Staat je keuze er niet tussen? Stuur dan /stop om opnieuw te beginnen_", update, context, reply_markup)

        # Return to the next state
        return context.user_data["option_state"]

    async def request_media_again(self, update: Update, context: CallbackContext):

        # Acknowledge the callback
        await update.callback_query.answer()

        if update.callback_query.data == "no":
            await self.function.send_message(f"Oke, je kan de bot altijd opnieuw starten door /start te sturen.", update, context)
            return ConversationHandler.END

        # Try again from start
        return await self.start.parse_request(update, context)

    async def media_option(self, update: Update, context: CallbackContext) -> Optional[int]:
        """ Handles the specific user media choice and downloads it """

        # Answer query and set media_data based on option number
        await update.callback_query.answer()
        context.user_data["media_data"] = context.user_data["media_object"][int(update.callback_query.data)]

        # Make transmission connection and get active torrent list
        try:
            ip = "0.0.0.0" if getattr(
                self.args, 'env', 'dev') == "live" else os.getenv('TRANSMISSION_IP')
            client = Client(host=ip, port=os.getenv('TRANSMISSION_PORT'), username=os.getenv(
                'TRANSMISSION_USER'), password=os.getenv('TRANSMISSION_PWD'))
            active_torrents = client.get_torrents(arguments=["name"])
        except Exception as e:
            await self.function.send_message(f"*😵 Er ging iets fout tijdens het maken van verbinding met de downløad client*\n\nDe serverbeheerder is op de hoogte gesteld van het probleem, je kan het nog een keer proberen in de hoop dat het dan wel werkt, of je kan het op een later moment nogmaals proberen.", update, context)
            await self.log.logger(f"There has been an error during the Transmission connection. See the logs for more info.\n\nError: {' '.join(e.args)}", False, "error", False)
            await self.log.logger(f"There has been an error during the Transmission connection. Error: {' '.join(e.args)}\nTraceback:\n{traceback.format_exc()}", False, "error")
            return ConversationHandler.END  # Quit if connection fails

        # Get the media states
        states = await self.get_media_states()

        # Loop through states
        for state, details in states.items():
            if details["condition"](context.user_data["media_data"], active_torrents):

                # Sanitize title and set a var
                context.user_data["media_data"]['title'] = self.function.sanitize_text(context.user_data["media_data"]['title'])

                # Do serie season size check if defined
                if "size_check" in details:
                    # Check if there are more than 6 seasons
                    if context.user_data["media_data"]["statistics"]["seasonCount"] > 5:
                        await self.function.send_message(f"Je hebt een serie aangevraagd die meer dan 5 seizoenen heeft, omdat de server opslag beperkt is zal deze aanvraag handmatig beoordeeld worden. Er bestaat een reële kans dat de serie hierdoor niet gedownløad zal worden.\n\nWil je de serie echt super graag op Plęx zien? Stuur dan een bericht door /help te sturen en te kiezen voor de optie: *📍 Anders*", update, context)
                        await asyncio.sleep(1)

                        # Do action but unmonitor serie
                        context.user_data["set_monitored"] = False
                        success = await getattr(self, details["action"])(update, context)
                        if not success:
                            # user was informerd in previous steps about the error
                            return ConversationHandler.END

                        # Send the notify message
                        await self.ask_notify_question(update, context, "notify", f"Wil je een melding ontvangen als {context.user_data["media_data"]['title']} online staat?")

                        # Info log
                        await self.log.logger(f"*⚠️ User has requested {context.user_data["media_data"]['title']} ({context.user_data["media_data"]['tmdbId']}) with {context.user_data["media_data"]['statistics']['seasonCount']} seasons ⚠️*\nGebruiker: {context.user_data["gebruiker"]}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")

                        # Write to stats file
                        await self.write_to_stats(update, context)

                        # Return to next state
                        return details["next_state"]

                # Do actions if defined
                if "action" in details:
                    success = await getattr(self, details["action"])(update, context)
                    if not success:
                        # user was informerd in previous steps about the error
                        return ConversationHandler.END

                # Do extra action if defined
                if "extra_action" in details:
                    await getattr(context.user_data["media_handler"], details["extra_action"])()

                # Inform owner about unmonitored series if defined
                if "inform_unmonitored" in details:
                    await self.log.logger(f"*ℹ️ User has requested {context.user_data["media_data"]['title']} which has been marked as unmonitored ℹ️*\nGebruiker verwacht reactie of het wel/niet gedownload gaat worden.\nGebruiker: {context.user_data["gebruiker"]}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "warn")

                # Send the message if defined
                if "message" in details:
                    await self.function.send_message(details["message"].format(title=context.user_data["media_data"]['title']), update, context)
                    await asyncio.sleep(1)

                # Only if media is already downloaded
                if state == "already_downloaded":

                    # Get the Plęx url of the media
                    media_plex_url = await self.plex.get_media_url(context.user_data["media_data"], context.user_data["label"])
                    if not media_plex_url:
                        await self.function.send_message(f"Zo te zien is {context.user_data["media_data"]['title']} al gedownløad.", update, context)
                    else:
                        await self.function.send_message(f"Zo te zien is {context.user_data["media_data"]['title']} al gedownløad.\n\n🌐 <a href='{media_plex_url}'>Bekijk {context.user_data["media_data"]['title']} in de browser</a>", update, context, None, "HTML")

                    # Send the notify message
                    await asyncio.sleep(1)
                    await self.ask_notify_question(update, context, "upgrade", f"Heb je {context.user_data["media_data"]['title']} aangevraagd omdat er iets mis is met de downløad? Bijvoorbeeld: \n- Slechte 720p kwaliteit\n- Ingebakken reclame\n- Chinese ondertiteling\n- Missende episode")

                    # Write to stats file
                    await self.write_to_stats(update, context)

                    # Send log
                    await self.log.logger(f"*ℹ️ User has requested {context.user_data["media_data"]['title']} - ({context.user_data["media_data"]['tmdbId']}) while it's already downløaded ℹ️*\nGebruiker: {context.user_data["gebruiker"]}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")

                    # Return the next specific state
                    return details["next_state"]

                # Send the question message for the next state
                if "state_message" in details:

                    # Send the notify message
                    await self.ask_notify_question(update, context, "notify", f"Wil je een melding ontvangen als {context.user_data["media_data"]['title']} online staat?")

                # Info log
                await self.log.logger(f"*ℹ️ User has requested the {context.user_data["label"]} {context.user_data["media_data"]['title']} - ({context.user_data["media_data"]['tmdbId']}) ℹ️*\nGebruiker: {context.user_data["gebruiker"]}\nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")

                # Write to stats file
                await self.write_to_stats(update, context)

                # Return the next specific state
                return details["next_state"]

        # Fallback error: if no state matches
        await self.function.send_message(f"*😵 Oeps, daar ging iets fout*\n\nDe serverbeheerder is op de hoogte gesteld van het probleem, je kan het nog een keer proberen in de hoop dat het dan wel werkt, of je kan het op een later moment nogmaals proberen.", update, context)
        await self.log.logger(f"Error happened during media state filtering, see the logs for the media JSON.", False, "error", True)
        await self.log.logger(f"Media JSON:\n{context.user_data["media_data"]}", False, "error", False)
        return ConversationHandler.END

    async def ask_notify_question(self, update: Update, context: CallbackContext, type: str, msg: str) -> None:
        """ Asks if the user want to stay notified about the download """

        # Create the keyboard
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Ja", callback_data=f"{context.user_data["label"]}_{type}_yes"),
                InlineKeyboardButton("Nee", callback_data=f"{context.user_data["label"]}_{type}_no")
            ]
        ])

        # Send the notify message
        await self.function.send_message(msg, update, context, reply_markup)

    async def stay_notified(self, update: Update, context: CallbackContext) -> None:
        """ Handles if the user wants te be updated about the requested media """

        # Answer query
        await update.callback_query.answer()

        # Finish conversation if chosen
        if update.callback_query.data == f"{context.user_data["label"]}_notify_no":
            await self.function.send_message(f"Oke, bedankt voor het gebruiken van deze bot. Wil je nog iets anders downløaden? Stuur dan /start", update, context)
            return ConversationHandler.END

        # Add media_id + user_id to JSON
        with open(self.data_json, "r+") as file:
            json_data = json.load(file)

            # Check if user already has entry in the notify list, otherwise create it
            if str(update.effective_user.id) not in json_data["notify_list"]:
                json_data["notify_list"][f"{update.effective_user.id}"] = {}

            # Check if serie/film block exists, otherwise create it
            for media_type in ["serie", "film"]:
                if media_type not in json_data["notify_list"][f"{update.effective_user.id}"]:
                    json_data["notify_list"][f"{update.effective_user.id}"][f"{media_type}"] = {}

            # Add media to notify_list
            json_data["notify_list"][f"{update.effective_user.id}"][f"{context.user_data["label"]}"][context.user_data["media_data"]["tmdbId"]] = round(time.time())

            # Write to the file
            file.seek(0)
            json.dump(json_data, file, indent=4)
            file.truncate()

        # Send final message
        await self.function.send_message(f"Oke, je ontvangt een melding als {context.user_data["media_data"]['title']} beschikbaar is. Wil je nog iets anders downløaden? Stuur dan /start", update, context)
        return ConversationHandler.END

    async def start_download(self, update: Update, context: CallbackContext) -> bool:
        """ Starts the download in Radarr or Sonarr """

        # Get folder to download to
        download_folder = await self.check_disk_space()

        # Check if enough space is left
        if not download_folder:
            await self.function.send_message(f"*😵 Er is op dit moment een probleem met de opslag van de Plęx server*\n\nDe serverbeheerder is hiervan op de hoogte en zal dit zo snel mogelijk oplossen. Probeer het op een later moment nog is.", update, context)
            await self.log.logger(f"Error happened during the check of the diskspace", False, "error", True)
            return False

        # Create the download payload
        try:
            set_monitored = context.user_data["set_monitored"]
        except NameError:
            set_monitored = True
        payload = await self.create_download_payload(context.user_data["media_data"], download_folder, set_monitored)

        # Check if payload creation was succesfull
        if not payload:
            await self.function.send_message(f"Er ging iets mis bij het starten van de downløad. De serverbeheerder is hiervan op de hoogte en zal dit zo snel mogelijk oplossen. Probeer het op een later moment nog is.", update, context)
            return False

        # Queue download
        response = await context.user_data["media_handler"].queue_download(payload)

        # Check if download queue was succesfull
        if not response:
            await self.function.send_message(f"Er ging iets mis bij het starten van de downløad. De serverbeheerder is hiervan op de hoogte en zal dit zo snel mogelijk oplossen. Probeer het op een later moment nog is.", update, context)
            return False

        return True

    async def check_disk_space(self) -> Optional[str]:
        """ Checks if the disk given in de .env file have enough space left """

        # Get list of disks and diskspace
        disk_list = context.user_data["media_folder"].split(",")
        disk_space = await context.user_data["media_handler"].get_disk_space()

        # TMP ALWAYS INSTANT RETURN MEDIE FOLDER SINCE ITS JUST /MEDIA/BEIDE/MOVIES4 OR /MEDIA/BEIDE/SERIES4
        await self.log.logger(disk_list[0], False, "error", False)
        return disk_list[0]

        # Check retrieve diskspace succesfull
        if not disk_space:
            await self.log.logger(f"Hier?", False, "error", True)
            return None

        # 100GB to bytes
        GB_100 = 100 * 1024 ** 3

        # Check each folder in JSON, return folder name if more then 100gb space left
        for folder in disk_list:
            for disk in disk_space:
                if disk["path"] == folder:
                    if disk["freeSpace"] > GB_100:
                        return disk["path"]

        # Return if no disks have more then 100gb left
        return None

    async def write_to_stats(self, update: Update, context: CallbackContext) -> None:
        """ Writes stats to the stats.json file """

        # Add media download requests to the stats
        try:
            with open(self.stats_json, "r+") as file:
                data = json.load(file)
                data[f"{update.effective_user.id}"][f"{context.user_data["label"]}_requests"][datetime.now().strftime("%d-%m-%Y %H:%M:%S")] = context.user_data["media_data"]['title']
                file.seek(0)
                json.dump(data, file, indent=4)
                file.truncate()
        except Exception as e:
            await self.log.logger(f"Error during write to stats.json for media {context.user_data["media_data"]['title']} and user {context.user_data["gebruiker"]}, username {update.effective_user.first_name}.\n\nError: {' '.join(e.args)}\nTraceback:\n{traceback.format_exc()}", False, "error", True)
