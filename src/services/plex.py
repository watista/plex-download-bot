#!/usr/bin/python3

import os
import traceback
from typing import Optional
from plexapi.server import PlexServer


class Plex:

    def __init__(self, logger):

        # Create the log class
        self.log = logger
        self.plex_server_id = os.getenv('PLEX_ID')
        self.plex = PlexServer(os.getenv('PLEX_URL'), os.getenv('PLEX_API'))

    async def get_media_url(self, media_data: dict, media_type: str) -> Optional[str]:
        """ Create's a Plex link to the media """

        # Set media type
        section = "Movies" if media_type == "film" else "TV Shows"

        # Check if media_data is a list or dict
        if isinstance(media_data, list):
            media_data = next(iter(media_data), {})

        # Ensure title exists
        title = media_data.get("title", "").strip()
        if not title:
            await self.log.logger("❌ *Error while creating a Plex link* ❌\n\nNo title is present in the JSON. Check the error log for more information.", False, "error")
            await self.log.logger(f"Full JSON output: {media_data}", False, "error", False)
            return None

        # Get movie by name from Plex
        media = self.plex.library.section(section).search(title)
        if not media:
            await self.log.logger(f"⚠️ *No Plex match found for '{title}'* ⚠️", False, "warning")
            return None

        # Create URL's if there is a match, otherwise throw error and return none
        try:
            return f"https://app.plex.tv/desktop/#!/server/{self.plex_server_id}/details?key=%2Flibrary%2Fmetadata%2F{media[0].ratingKey}"
        except (IndexError, KeyError):
            await self.log.logger(f"❌ *No valid media found in Plex for '{title}'* ❌\n\nCheck the error log for more information.", False, "error")
        except Exception as e:
            await self.log.logger(f"❌ *Error while creating a Plex link* ❌\n\nCheck the error log for more information.", False, "error")
            await self.log.logger(f"Unexpected error while creating Plex link: {e}", False, "error")
            await self.log.logger(f"Traceback: {traceback.format_exc()}", False, "error", False)
            await self.log.logger(f"Full JSON output: {media_data}", False, "error", False)

        return None
