#!/usr/bin/python3

import requests
import json
import os

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
    async def lookup_by_name(self, media_name: str):
        """ Abstract method that does a media lookup in the subclass """
        pass


    @abstractmethod
    async def queue_download(self, payload):
        """ Abstract method that starts a download in the subclass """
        pass


    @abstractmethod
    async def scan_missing_media(self):
        """ Abstract method that scans for missing monitored media in the subclass """
        pass


    async def get(self, url_string: str): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?
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
            await self.log.logger(f"Fout opgetreden tijdens een {self.label} api GET. Error: {' '.join(e.args)} - Url: {url}", False, "error", False)
            return False


    async def post(self, url_string: str, payload): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?
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
            await self.log.logger(f"Fout opgetreden tijdens een {self.label} api POST. Error: {' '.join(e.args)} - Url: {url}", False, "error", False)
            return False


    async def get_disk_space(self): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?
        """ Makes a GET request to get the disk space """

        # Build url_string and make the request
        disks = await self.get(f"/diskspace?")

        # Check if return value is empty
        if not disks:
            await self.log.logger(f"❌ *Error while fetching {self.label} diskspace information.* Check the error log for more information. ❌", False, "error")
            return {}

        # Return the data
        return disks.json()
