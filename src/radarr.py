#!/usr/bin/python3

import requests
import json
import os


class Radarr:


    def __init__(self, logger):

        # Create the log class
        self.log = logger
        self.token = os.getenv('RADARR_API')
        self.radarr_url = "https://radarr.wouterpaas.nl/api/v3"


    async def get(self, url_string: str): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?

        # Build request URL
        url = self.radarr_url + url_string + "&apikey=" + self.token

        # Make the request
        try:
            response = requests.request("GET", url, headers={}, data={})

            # Log and send Telegram message if request was unsuccesfull
            if not response.ok:
                await self.log.logger(f"Not OK response for Radarr api GET. Error: {response.status_code} {response.reason} {response.text} - Url: {url}", False, "error", False)
                return False

            # Return the response if request was succesfull
            return response

        # Log and send Telegram message if anything went wrong
        except Exception as e:
            await self.log.logger(f"Fout opgetreden tijdens een Radarr api GET. Error: {' '.join(e.args)} - Url: {url}", False, "error", False)
            return False


    async def post(self, url_string: str, payload): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?

        # Build request URL
        url = self.radarr_url + url_string + "&apikey=" + self.token

        # Make the request
        try:
            response = requests.request("POST", url, headers={'Content-Type': 'application/json'}, json=payload)

            # Log and send Telegram message if request was unsuccesfull
            if not response.ok:
                await self.log.logger(f"Not OK response for Radarr api POST. Error: {response.status_code} {response.reason} {response.text} - Url: {url}", False, "error", False)
                return False

            # Return the response if request was succesfull
            return response

        # Log and send Telegram message if anything went wrong
        except Exception as e:
            await self.log.logger(f"Fout opgetreden tijdens een Radarr api POST. Error: {' '.join(e.args)} - Url: {url}", False, "error", False)
            return False

    async def lookup_by_name(self, movie_name: str): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?

        # Build url_string and make the request
        lookup = await self.get(f"/movie/lookup?term={movie_name}")

        # Check if return value is empty
        if not lookup:
            await self.log.logger(f"❌ *Error while fetching movie list for term {movie_name}.* Check the error log for more information\. ❌", False, "error")
            return {}

        # Return the data
        return lookup.json()


    async def get_disk_space(self): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?

        # Build url_string and make the request
        disks = await self.get(f"/diskspace?")

        # Check if return value is empty
        if not disks:
            await self.log.logger(f"❌ *Error while fetching movie diskspace information.* Check the error log for more information. ❌", False, "error")
            return {}

        # Return the data
        return disks.json()


    async def queue_download(self, payload): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?

        # Build url_string and make the request
        response = await self.post(f"/movie?", payload)

        # Check if return value is empty
        if not response:
            await self.log.logger(f"❌ *Error while queueing download.* Check the error log for more information. ❌", False, "error")
            return {}

        # Return the data
        return response.json()


    async def scan_missing_movies(self): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?

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
