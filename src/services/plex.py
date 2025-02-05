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


    # async def get(self, url_string: str): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?
    #     """ Handles the GET requests """

    #     # Build request URL
    #     url = self.base_url + url_string

    #     # Create headers
    #     headers = {"X-Plex-Token": self.api_key}

    #     # Make the request
    #     try:
    #         response = requests.request("GET", url, headers={headers}, data={})

    #         # Log and send Telegram message if request was unsuccesfull
    #         if not response.ok:
    #             await self.log.logger(f"Not OK response for {self.label} api GET. Error: {response.status_code} {response.reason} {response.text} - Url: {url}", False, "error", False)
    #             return False

    #         # Return the response if request was succesfull
    #         return response

    #     # Log and send Telegram message if anything went wrong
    #     except Exception as e:
    #         await self.lo


    async def get_media_url(self, media_data, media_type: str) -> list: # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?
        """ Create's a Plex link to the media """

        # Set media type
        if media_type == "film":
            section = "Movies"
        else:
            section = "TV Shows"

        # Get movie by name from Plex
        media = self.plex.library.section(section).search(title=media_data['title'])

        # Create URL's if there is a match, otherwise throw error and return empty list
        try:
            link = f"https://app.plex.tv/desktop/#!/server/{self.plex_server_id}/details?key=%2Flibrary%2Fmetadata%2F" + str(media[0].ratingKey)
            return [link]
        except Exception as e:
            await self.log.logger(f"❌ *Error while creating a Plex link* ❌\n\nCheck the error log for more information.", False, "error")
            await self.log.logger(f"Fout opgetreden tijdens het maken van een Plex link. Error: {' '.join(e.args)} - Traceback: {traceback.format_exc()}", False, "error", False)
            return []


    async def scan_new_files(self): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?
        url = "https://app.plex.tv/desktop/#!/server/20ebc684cd38daa9b44ba16faf2fbe7709232492/details?key=%2Flibrary%2Fmetadata%2F" + "movie rating key"
