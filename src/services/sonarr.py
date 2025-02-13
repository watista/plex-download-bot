#!/usr/bin/python3

import json
import os
from typing import Union
from src.services.arr import ArrApiHandler


class Sonarr(ArrApiHandler):
    """ Specific class for the Radarr API """

    def __init__(self, logger):
        super().__init__(logger, os.getenv('SONARR_API'), os.getenv('SONARR_URL'), "serie")

    async def lookup_by_name(self, serie_name: str) -> Union[list[dict], dict]:
        """ Function that does a serie lookup """

        # Build url_string and make the request
        response = await self.get(f"/series/lookup?term={serie_name}")

        # Check if return value is empty
        if not response:
            await self.log.logger(f"❌ *Error while fetching serie list for term {serie_name}.* Check the error log for more information. ❌", False, "error")
            return None

        # Return the data
        return response

    async def queue_download(self, payload: dict) -> Union[list[dict], dict]:
        """ Function that starts a download """

        # Build url_string and make the request
        response = await self.post(f"/series?", payload)

        # Check if return value is empty
        if not response:
            await self.log.logger(f"❌ *Error while queueing serie download.* Check the error log for more information. ❌", False, "error")
            return None

        # Return the data
        return response

    async def scan_missing_media(self) -> Union[list[dict], dict]:
        """ Function that scans for missing monitored series """

        # Set payload
        payload = {"name": "MissingEpisodeSearch",
                   "filterKey": "monitored", "filterValue": "true"}

        # Build url_string and make the request
        response = await self.post(f"/command?", payload)

        # Check if return value is empty
        if not response:
            await self.log.logger(f"❌ *Error while scanning for missing series.* Check the error log for more information. ❌", False, "warning")
            return None

        # Return the data
        return response
