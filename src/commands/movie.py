#!/usr/bin/python3

import asyncio

from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler


class Movie:

    def __init__(self, logger, functions, radarr):

        # Set default values
        self.log = logger
        self.function = functions
        self.radarr = radarr


    async def request_movie(self, update: Update, context: CallbackContext) -> None:

        # Send start message
        await self.function.send_message(f"Oke, je wilt dus graag {update.message.text} op Plex zien. Even kijken of dat mogelijk is...", update, context)
        await asyncio.sleep(1)

        # Make the API request
        movies = await self.radarr.lookup_by_name(update.message.text)

        if not movies:
            await self.function.send_message(f"Er zijn geen resultaten gevonden voor de film {update.message.text}. Misschien heb je een typfout gemaakt in de titel? Je kan het nogmaals proberen door /start te sturen.", update, context)
            return ConversationHandler.END

        await self.function.send_message(f"De volgende films zijn gevonden met de term {update.message.text}:", update, context)
        await asyncio.sleep(1)

        await self.function.send_image(f"*{movies[0]['title']} ({movies[0]['year']})*\n\n{movies[0]['overview']}", movies[0]['remotePoster'], update, context)
        await asyncio.sleep(1)
        await self.function.send_image(f"*{movies[1]['title']} ({movies[1]['year']})*\n\n{movies[1]['overview']}", movies[1]['remotePoster'], update, context)
        await asyncio.sleep(1)
        await self.function.send_image(f"*{movies[2]['title']} ({movies[2]['year']})*\n\n{movies[2]['overview']}", movies[2]['remotePoster'], update, context)
        await asyncio.sleep(1)

