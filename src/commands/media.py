#!/usr/bin/python3

import asyncio
import os
import json
from transmission_rpc import Client
from abc import ABC, abstractmethod

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext, ConversationHandler


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


    @abstractmethod
    async def get_media_states(self):
        """ Abstract method that defines the states in the subclasses """
        pass


    async def request_media(self, update: Update, context: CallbackContext) -> int:
        """ Handles the parsing of the chosen media and gives the options for which one the user wants """

        # Send start message
        await self.function.send_message(f"Oke, je wilt dus graag {update.message.text} op Plex zien. Even kijken of dat mogelijk is...", update, context)
        await asyncio.sleep(1)

        # Make the API request
        self.media = await self.media_handler.lookup_by_name(update.message.text)

        # End conversation if no results are found
        if not self.media:
            await self.function.send_message(f"Er zijn geen resultaten gevonden voor de {self.label} {update.message.text}. Misschien heb je een typfout gemaakt in de titel? Je kan het nogmaals proberen door /start te sturen.", update, context)
            return ConversationHandler.END

        await self.function.send_message(f"De volgende {self.label}s zijn gevonden met de term {update.message.text}:", update, context)
        await asyncio.sleep(1)

        # Set counter
        counter = 0

        # Loop to all media hits with a max of 5
        for item in self.media[:5]:

            # Get the values with backup if non-existing
            title = item.get('title', update.message.text)
            year = item.get('year', 'Jaartal onbekend')
            overview = item.get('overview', 'Geen beschrijving beschikbaar')
            remote_poster = item.get('remotePoster')

            # Send message based on remote_poster availability
            if remote_poster:
                await self.function.send_image(f"*Optie {counter + 1} - {title} ({year})*\n\n{overview}", remote_poster, update, context)
            else:
                await self.function.send_message(f"*Optie {counter + 1} - {title} ({year})*\n\n{overview}", update, context)

            # Bump counter
            counter += 1
            await asyncio.sleep(1)

        # Create the options keyboard
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"Optie {i + 1}", callback_data=f"{i}")
                for i in range(len(self.media[:2]))
            ],
            [
                InlineKeyboardButton(f"Optie {i + 3}", callback_data=f"{i + 2}")
                for i in range(len(self.media[2:4]))
            ],
            [
                InlineKeyboardButton(f"Optie {i + 5}", callback_data=f"{i + 4}")
                for i in range(len(self.media[4:5]))
            ]
        ])

        # Send the message with the keyboard options
        await self.function.send_message(f"Welke optie wil je graag op Plex zien?", update, context, reply_markup)

        # Return to the next state
        return self.option_state


    async def media_option(self, update: Update, context: CallbackContext) -> int:
        """ Handles the specific user media choice and downloads it """

        # Answer query and set media_data based on option number
        await update.callback_query.answer()
        self.media_data = self.media[int(update.callback_query.data)]

        # Make transmission connection and get active torrent list
        try:
            ip = "0.0.0.0" if getattr(self.args, 'env', 'dev') == "live" else "192.168.1.111"
            client = Client(host=ip, port=9091, username="wouter", password=os.getenv('TRANSMISSION_PWD'))
            active_torrents = client.get_torrents(arguments=["name"])
        except Exception as e:
            await self.function.send_message(f"*😵 Er ging iets fout tijdens het maken van verbinding met de download client*\n\nDe serverbeheerder is op de hoogte gesteld van het probleem, je kan het nog een keer proberen in de hoop dat het dan wel werkt, of je kan het op een later moment nogmaals proberen.", update, context)
            await self.log.logger(f"Fout opgetreden tijdens verbinding maken met Transmission. Error: {' '.join(e.args)}", False, "error", True)
            return ConversationHandler.END  # Quit if connection fails

        # Get the media states
        states = await self.get_media_states()

        # Loop through states
        for state, details in states.items():
            if details["condition"](self.media_data, active_torrents):

                # Do actions if defined
                if "action" in details:
                    success = await getattr(self, details["action"])()
                    if not success:
                        return ConversationHandler.END  # Quit if download fails

                # Do extra action if defined
                if "extra_action" in details:
                    await getattr(self.media_handler, details["extra_action"])()

                # Send the message
                await self.function.send_message(details["message"].format(title=self.media_data['title']), update, context)
                await asyncio.sleep(1)

                # Send the question message for the next state
                if "state_message" in details:

                    # Create the keyboard
                    reply_markup = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("Ja", callback_data=f"{self.label}_yes"),
                            InlineKeyboardButton("Nee", callback_data=f"{self.label}_no")
                        ]
                    ])
                    await self.function.send_message(f"Wil je een melding ontvangen als {self.media_data['title']} online staat?", update, context, reply_markup)

                    # Info log
                    await self.log.logger(f"Gebruiker heeft {self.media_data['title']} aangevraagd \nUsername: {update.effective_user.first_name}\nUser ID: {update.effective_user.id}", False, "info")

                return details["next_state"]

        # Fallback error: if no state matches
        await self.function.send_message(f"*😵 Oeps, daar ging iets fout*\n\nDe serverbeheerder is op de hoogte gesteld van het probleem, je kan het nog een keer proberen in de hoop dat het dan wel werkt, of je kan het op een later moment nogmaals proberen.", update, context)
        await self.log.logger(f"Error happened during media state filtering, see the logs for the media JSON.", False, "error", True)
        await self.log.logger(f"Media JSON:\n{self.media_data}", False, "error", False)
        return ConversationHandler.END


    async def stay_notified(self, update: Update, context: CallbackContext) -> int:
        """ Handles if the user wants te be updated about the requested media """

        # Answer query
        await update.callback_query.answer()

        # Finish conversation if chosen
        if update.callback_query.data == f"{self.label}_no":
            await self.function.send_message(f"Oke, bedankt voor het gebruiken van deze bot. Wil je nog iets anders downloaden? Stuur dan /start", update, context)
            return ConversationHandler.END

        # Add media_id + user_id to JSON
        with open("data.json", "r+") as file:
            json_data = json.load(file)
            json_data["notify_list"][self.media_data["tmdbId"]] = update.effective_user.id
            file.seek(0)
            json.dump(json_data, file, indent=4)
            file.truncate()

        # Send final message
        await self.function.send_message(f"Oke, je ontvangt een melding als {self.media_data['title']} beschikbaar is. Wil je nog iets anders downloaden? Stuur dan /start", update, context)
        return ConversationHandler.END


    async def start_download(self):
        """ Starts the download in Radarr or Sonarr """

        # Get folder to download to
        download_folder = await self.check_disk_space()

        # Check if enough space is left
        if not download_folder:
            await self.function.send_message(f"*😵 Er is op dit moment een probleem met de opslag van de Plex server*\n\nDe serverbeheerder is hiervan op de hoogte en zal dit zo snel mogelijk oplossen. Probeer het op een later moment nog is.", update, context)
            await self.log.logger(f"Fout opgetreden tijdens de controle van de diskspace.", False, "error", True)
            return False

        # Create the download payload
        payload = {
            "qualityProfileId": 7,
            "monitored": True,
            "tmdbId": self.media_data['tmdbId'],
            "rootFolderPath": download_folder
        }

        # Queue download
        response = await self.media_handler.queue_download(payload)

        # Check if download queue was succesfull
        if not response:
            await self.function.send_message(f"Er ging iets miss bij het starten van de download. De serverbeheerder is hiervan op de hoogte en zal dit zo snel mogelijk oplossen. Probeer het op een later moment nog is.", update, context)
            return False

        return True


    async def check_disk_space(self):
        """ Checks if the disk given in de .env file have enough space left """

        # Get list of disks and diskspace
        disk_list = self.media_folder.split(",")
        disk_space = await self.media_handler.get_disk_space()

        # Check retrieve diskspace succesfull
        if not disk_space:
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
