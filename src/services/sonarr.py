#!/usr/bin/python3

import requests
import json
import os

from src.services.arr import Arr


class Sonarr(Arr):
    """ Specific class for the Radarr API """

    def __init__(self, logger):
        super().__init__(logger, os.getenv('SONARR_API'), "https://sonarr.wouterpaas.nl/api/v3", "serie")


    async def lookup_by_name(self, serie_name: str): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?
        """ Function that does a serie lookup """

        # Build url_string and make the request
        lookup = await self.get(f"/series/lookup?term={serie_name}")

        # Check if return value is empty
        if not lookup:
            await self.log.logger(f"❌ *Error while fetching serie list for term {serie_name}.* Check the error log for more information. ❌", False, "error")
            return {}

        # Return the data
        return lookup.json()


    async def queue_download(self, payload): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?
        """ Function that starts a download """

        # Build url_string and make the request
        response = await self.post(f"/series?", payload)

        # Check if return value is empty
        if not response:
            await self.log.logger(f"❌ *Error while queueing serie download.* Check the error log for more information. ❌", False, "error")
            return {}

        # Return the data
        return response.json()


    async def scan_missing_media(self): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?
        """ Function that scans for missing monitored series """

        # Set payload
        payload = {"name":"MissingEpisodeSearch","filterKey":"monitored","filterValue":"true"}

        # Build url_string and make the request
        response = await self.post(f"/command?", payload)

        # Check if return value is empty
        if not response:
            await self.log.logger(f"❌ *Error while scanning for missing series.* Check the error log for more information. ❌", False, "warning")
            return {}

        # Return the data
        return response.json()
