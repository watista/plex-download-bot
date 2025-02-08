#!/usr/bin/python3

import requests
import json
import os
from typing import Union
from src.services.arr import Arr


class Radarr(Arr):
    """ Specific class for the Radarr API """

    def __init__(self, logger):
        super().__init__(logger, os.getenv('RADARR_API'), os.getenv('RADARR_URL'), "movie")


    async def lookup_by_name(self, movie_name: str) -> Union[list[dict], dict]:
        """ Function that does a movie lookup """

        # Build url_string and make the request
        lookup = await self.get(f"/movie/lookup?term={movie_name}")

        # Check if return value is empty
        if not lookup:
            await self.log.logger(f"❌ *Error while fetching movie list for term {movie_name}.* Check the error log for more information. ❌", False, "error")
            return {}

        # Return the data
        return lookup.json()


    async def queue_download(self, payload: dict) -> Union[list[dict], dict]:
        """ Function that starts a download """

        # Build url_string and make the request
        response = await self.post(f"/movie?", payload)

        # Check if return value is empty
        if not response:
            await self.log.logger(f"❌ *Error while queueing movie download.* Check the error log for more information. ❌", False, "error")
            return {}

        # Return the data
        return response.json()


    async def scan_missing_media(self) -> Union[list[dict], dict]:
        """ Function that scans for missing monitored movies """

        # Set payload
        payload = {"name":"missingMoviesSearch","filterKey":"monitored","filterValue":"true"}

        # Build url_string and make the request
        response = await self.post(f"/command?", payload)

        # Check if return value is empty
        if not response:
            await self.log.logger(f"❌ *Error while scanning for missing movies.* Check the error log for more information. ❌", False, "warning")
            return {}

        # Return the data
        return response.json()
