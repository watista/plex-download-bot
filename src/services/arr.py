#!/usr/bin/python3

import requests
import json
import traceback
from typing import Union
from abc import ABC, abstractmethod


class Arr(ABC):
    """ Base class for usage of the Radarr/Sonarr API """

    def __init__(self, logger, token, base_url, label):

        # Init the class
        self.log = logger
        self.token = token
        self.base_url = base_url
        self.label = label


    @abstractmethod
    async def lookup_by_name(self, media_name: str) -> Union[list[dict], dict]:
        """ Abstract method that does a media lookup in the subclass """
        pass


    @abstractmethod
    async def queue_download(self, payload: dict) -> Union[list[dict], dict]:
        """ Abstract method that starts a download in the subclass """
        pass


    @abstractmethod
    async def scan_missing_media(self) -> Union[list[dict], dict]:
        """ Abstract method that scans for missing monitored media in the subclass """
        pass


    async def get(self, url_string: str) -> Union[requests.Response, bool]:
        """ Handles the GET requests """

        # Build request URL
        url = self.base_url + url_string + "&apikey=" + self.token

        # Make the request
        try:
            response = requests.request("GET", url, headers={}, data={})

            # Log and send Telegram message if request was unsuccesfull
            if not response.ok:
                await self.log.logger(f"Not OK response for {self.label} api GET. Error: {response.status_code} {response.reason} {response.text} - Url: {url}", False, "error", False)
                return False

            # Return the response if request was succesfull
            return response

        # Log and send Telegram message if anything went wrong
        except Exception as e:
            await self.log.logger(f"Error during a {self.label} api GET request. Error: {' '.join(e.args)} - Traceback: {traceback.format_exc()} - Url: {url}", False, "error", False)
            return False


    async def post(self, url_string: str, payload: dict) -> Union[requests.Response, bool]:
        """ Handles the POST requests """

        # Build request URL
        url = self.base_url + url_string + "&apikey=" + self.token

        # Make the request
        try:
            response = requests.request("POST", url, headers={'Content-Type': 'application/json'}, json=payload)

            # Log and send Telegram message if request was unsuccesfull
            if not response.ok:
                await self.log.logger(f"Not OK response for {self.label} api POST. Error: {response.status_code} {response.reason} {response.text} - Url: {url}", False, "error", False)
                return False

            # Return the response if request was succesfull
            return response

        # Log and send Telegram message if anything went wrong
        except Exception as e:
            await self.log.logger(f"Error during a {self.label} api POST request. Error: {' '.join(e.args)} - Traceback: {traceback.format_exc()} - Url: {url}", False, "error", False)
            return False


    async def get_disk_space(self) -> Union[list[dict], dict]:
        """ Makes a GET request to get the disk space """

        # Build url_string and make the request
        disks = await self.get(f"/diskspace?")

        # Check if return value is empty
        if not disks:
            await self.log.logger(f"❌ *Error while fetching {self.label} diskspace information.* Check the error log for more information. ❌", False, "error")
            return {}

        # Return the data
        return disks.json()


    async def lookup_by_tmdbid(self, tmdbid: str) -> Union[list[dict], dict]:
        """ Function that does a movie lookup by The Movie Database ID """

        # Create the correct url label
        url_label = "series" if self.label == "serie" else "movie"

        # Build url_string and make the request
        lookup = await self.get(f"/{url_label}/lookup?term=tmdb:{tmdbid}")

        # Check if return value is empty
        if not lookup:
            await self.log.logger(f"❌ *Error while fetching {self.label} with TMDB ID {tmdbid}.* Check the error log for more information. ❌", False, "error")
            return {}

        # Return the data
        return lookup.json()
