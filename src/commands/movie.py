#!/usr/bin/python3

import asyncio
import os
from transmission_rpc import Client

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext, ConversationHandler

from src.commands.states import MOVIE_OPTION


class Movie:

    def __init__(self, args, logger, functions, radarr):

        # Set default values
        self.args = args
        self.log = logger
        self.function = functions
        self.radarr = radarr


    async def request_movie(self, update: Update, context: CallbackContext) -> None:

        # Send start message
        await self.function.send_message(f"Oke, je wilt dus graag {update.message.text} op Plex zien. Even kijken of dat mogelijk is...", update, context)
        await asyncio.sleep(1)

        # Make the API request
        self.movies = await self.radarr.lookup_by_name(update.message.text)

        # End conversation if no results are found
        if not self.movies:
            await self.function.send_message(f"Er zijn geen resultaten gevonden voor de film {update.message.text}. Misschien heb je een typfout gemaakt in de titel? Je kan het nogmaals proberen door /start te sturen.", update, context)
            return ConversationHandler.END

        await self.function.send_message(f"De volgende films zijn gevonden met de term {update.message.text}:", update, context)
        await asyncio.sleep(1)

        # Set counter
        counter = 0

        # Loop to all movie hits with a max of 5
        for item in self.movies[:5]:

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
                for i in range(len(self.movies[:2]))
            ],
            [
                InlineKeyboardButton(f"Optie {i + 3}", callback_data=f"{i + 2}")
                for i in range(len(self.movies[2:4]))
            ],
            [
                InlineKeyboardButton(f"Optie {i + 5}", callback_data=f"{i + 4}")
                for i in range(len(self.movies[4:5]))
            ]
        ])

        # Send the message with the keyboard options
        await self.function.send_message(f"Welke optie wil je graag op Plex zien?", update, context, reply_markup)

        # Return to the next state
        return MOVIE_OPTION


    async def movie_option(self, update: Update, context: CallbackContext) -> None:

        # Answer query and set movie_data based on option number
        await update.callback_query.answer()
        movie_data = self.movies[int(update.callback_query.data)]

        # Make transmission connection and get active torrent list
        ip = "0.0.0.0" if getattr(self.args, 'env', 'dev') == "live" else "192.168.1.111"
        client = Client(host=ip, port=9091, username="wouter", password=os.getenv('TRANSMISSION_PWD'))
        active_torrents = client.get_torrents(arguments=["name"])

        # state - downloading
        if any(movie_data["title"].lower() in t.name.lower() for t in active_torrents):
            print("wordt op dit moment al gedownload")

        # state - not downloaded + not monitored + not available for download
        elif movie_data.get("movieFileId") == 0 and not movie_data.get("monitored") and movie_data.get("status") != "released":
            print("staat nog niet op de lijst, kan nog niet meteen gedownload worden")

        # state - not downloaded + not monitored + available for download
        elif movie_data.get("movieFileId") == 0 and not movie_data.get("monitored") and movie_data.get("status") == "released":
            print("staat nog niet op de lijst, wordt meteen gedownload")

        # state - not downloaded + monitored + not available for download
        elif movie_data.get("movieFileId") == 0 and movie_data.get("monitored") and movie_data.get("status") != "released":
            print("staat al op de lijst, kan nog niet gedownload worden")

        # state - not downloaded + monitored + available to download
        elif movie_data.get("movieFileId") == 0 and movie_data.get("monitored") and movie_data.get("status") == "released":
            print("staat al op de lijst, kan ook al gedownload worden dus dat is een probleem wss")

        # state - downloaded + monitored
        elif movie_data.get("movieFileId") != 0 and movie_data.get("monitored"):
            print("is al gedownload")

        # should not happen
        else:
            await self.function.send_message(f"*😵 *Oeps, daar ging iets fout*\n\nDe serverbeheerder is op de hoogte gesteld van het probleem, je kan het nog een keer proberen in de hoop dat het dan wel werkt, of je kan het op een later moment nogmaals proberen.", update, context)
            await self.log.logger(f"Error happened during movie state filtering, see the logs for the movie JSON.", False, "error", True)
            await self.log.logger(f"Movie JSON:\n{movie_data}", False, "error", False)
            return ConversationHandler.END
