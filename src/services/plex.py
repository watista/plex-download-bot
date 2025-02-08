#!/usr/bin/python3

import os
import traceback

from plexapi.server import PlexServer

class Plex:


    def __init__(self, logger):

        # Create the log class
        self.log = logger
        self.plex_server_id = os.getenv('PLEX_ID')
        self.plex = PlexServer(os.getenv('PLEX_URL'), os.getenv('PLEX_API'))


    async def get_media_url(self, media_data: dict, media_type: str) -> list:
        """ Create's a Plex link to the media """

        # Set media type
        section = "Movies" if media_type == "film" else "TV Shows"

        # Get movie by name from Plex
        media = self.plex.library.section(section).search(title=media_data[0]['title'])

        # Create URL's if there is a match, otherwise throw error and return empty list
        try:
            return [f"https://app.plex.tv/desktop/#!/server/{self.plex_server_id}/details?key=%2Flibrary%2Fmetadata%2F" + str(media[0].ratingKey)]
        except Exception as e:
            await self.log.logger(f"❌ *Error while creating a Plex link* ❌\n\nCheck the error log for more information.", False, "error")
            await self.log.logger(f"Error during the creating of the Plex link. Error: {' '.join(e.args)} - Traceback: {traceback.format_exc()}", False, "error", False)
            return []
