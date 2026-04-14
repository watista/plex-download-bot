#!/usr/bin/python3

import aiohttp
import json
import traceback
import asyncio
from typing import Union
from abc import ABC, abstractmethod
from aiohttp import ClientError, ClientTimeout, ContentTypeError


class ArrApiHandler(ABC):
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

    async def get(self, url_string: str) -> Union[dict, bool]:
        """ Handles the GET requests asynchronously using aiohttp """

        # Build request URL (apikey via params to avoid leaking in logs)
        url = f"{self.base_url}{url_string}"
        params = {"apikey": self.token}
        timeout = ClientTimeout(total=30)

        # Make the async request
        for attempt in range(1, 3 + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, params=params) as response:

                        # Continue if 2xx
                        if 200 <= response.status < 300:
                            try:
                                return await response.json()
                            except ContentTypeError:
                                # Some endpoints may return non-JSON on success
                                return {"raw": await response.text()}

                        # Retry if 5xx
                        if response.status in (500, 502, 503, 504):
                            if attempt < 3:
                                await asyncio.sleep(3)
                                continue
                            else:
                                await self.log.logger(
                                    f"Not OK response for {self.label} API GET after 3 retries. Last error: {response.status} {response.reason} {await response.text()} - URL: {url}",
                                    True, "error", False
                                )
                                return False

                        # Return false in other cases not OK
                        await self.log.logger(
                            f"Not OK response for {self.label} API GET. Error: {response.status} {response.reason} {await response.text()} - URL: {url}",
                            False, "error", False
                        )
                        return False

            # Log and send Telegram message if anything went wrong
            except (ClientError, asyncio.TimeoutError) as e:

                if attempt < 3:
                    await asyncio.sleep(3)
                    continue

                await self.log.logger(
                    f"Error during {self.label} API GET request. Error: {' '.join(map(str, e.args))} - Traceback: {traceback.format_exc()} - URL: {url}",
                    False, "error", False
                )
                return False
            except Exception as e:
                await self.log.logger(
                    f"Unexpected error during {self.label} API GET request. Error: {' '.join(map(str, e.args))} - Traceback: {traceback.format_exc()} - URL: {url}",
                    False, "error", False
                )
                return False

    async def post(self, url_string: str, payload: dict) -> Union[dict, bool]:
        """ Handles the POST requests asynchronously using aiohttp """

        # Build request URL (apikey via params to avoid leaking in logs)
        url = f"{self.base_url}{url_string}"
        params = {"apikey": self.token}
        timeout = ClientTimeout(total=30)

        # Make the async request
        for attempt in range(1, 3 + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, params=params, json=payload) as response:
                        # Continue if 2xx
                        if 200 <= response.status < 300:
                            try:
                                return await response.json()
                            except ContentTypeError:
                                return {"raw": await response.text()}

                        # Retry if 5xx
                        if response.status in (500, 502, 503, 504) and attempt < 3:
                            await asyncio.sleep(3)
                            continue

                        await self.log.logger(
                            f"Not OK response for {self.label} API POST. Error: {response.status} {response.reason} {await response.text()} - URL: {url} - Payload: {payload}",
                            False, "error", False
                        )
                        return False

            except (ClientError, asyncio.TimeoutError) as e:
                if attempt < 3:
                    await asyncio.sleep(3)
                    continue
                await self.log.logger(
                    f"Error during {self.label} API POST request. Error: {' '.join(map(str, e.args))} - Traceback: {traceback.format_exc()} - URL: {url} - Payload: {payload}",
                    False, "error", False
                )
                return False
            except Exception as e:
                await self.log.logger(
                    f"Unexpected error during {self.label} API POST request. Error: {' '.join(map(str, e.args))} - Traceback: {traceback.format_exc()} - URL: {url} - Payload: {payload}",
                    False, "error", False
                )
                return False

    async def get_disk_space(self) -> Union[list[dict], dict]:
        """ Makes a GET request to get the disk space """

        # Build url_string and make the request
        disks = await self.get(f"/diskspace?")

        # Check if return value is empty
        if not disks:
            await self.log.logger(f"❌ *Error while fetching {self.label} diskspace information.*\nCheck the error log for more information. ❌", False, "error")
            await self.log.logger(f"Response: {disks}", False, "error", False)
            return None

        # Return the data
        return disks

    async def lookup_by_tmdbid(self, tmdbid: str) -> Union[list[dict], dict]:
        """ Function that does a movie lookup by The Movie Database ID """

        # Create the correct url label
        url_label = "series" if self.label == "serie" else "movie"

        # Build url_string and make the request
        lookup = await self.get(f"/{url_label}/lookup?term=tmdb:{tmdbid}")

        # Check if return value is empty
        if not lookup:
            await self.log.logger(f"❌ *Error while fetching {self.label} with TMDB ID {tmdbid}.*\nCheck the error log for more information. ❌", False, "error")
            await self.log.logger(f"Response: {lookup}", False, "error", False)
            return None

        # Return the data
        return lookup
