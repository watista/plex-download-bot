#!/usr/bin/python3

import json
import os
from typing import Union
from src.services.arr import ArrApiHandler


class Radarr(ArrApiHandler):
    """ Specific class for the Radarr API """

    def __init__(self, logger):
        super().__init__(logger, os.getenv('RADARR_API'), os.getenv('RADARR_URL'), "movie")

    async def lookup_by_name(self, movie_name: str) -> Union[list[dict], dict]:
        """ Function that does a movie lookup """

        # Build url_string and make the request
        response = await self.get(f"/movie/lookup?term={movie_name}")

        # Check if return value is empty
        if response is False:
            await self.log.logger(f"❌ *Error while fetching movie list for term {movie_name}.* ❌\nCheck the error log for more information.", False, "error")
            await self.log.logger(f"Response: {response}", False, "error", False)
            return None

        # Return the data
        return response

    async def queue_download(self, payload: dict) -> Union[list[dict], dict]:
        """ Function that starts a download """

        # Build url_string and make the request
        response = await self.post(f"/movie?", payload)

        # Check if return value is empty
        if response is False:
            await self.log.logger(f"❌ *Error while queueing movie downløad.* ❌\nCheck the error log for more information.", False, "error")
            await self.log.logger(f"Response: {response}", False, "error", False)
            return None

        # Return the data
        return response

    async def scan_missing_media(self, context=None) -> Union[list[dict], dict]:
        """ Function that scans for missing monitored movies """

        # Set payload
        payload = {"name": "missingMoviesSearch",
                   "filterKey": "monitored", "filterValue": "true"}

        # Build url_string and make the request
        response = await self.post(f"/command?", payload)

        # Check if return value is empty
        if response is False:
            await self.log.logger(f"❌ *Error while scanning for missing movies.* ❌\nCheck the error log for more information.", False, "warning")
            await self.log.logger(f"Response: {response}", False, "error", False)
            return None

        # Return the data
        return response
