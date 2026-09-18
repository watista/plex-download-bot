#!/usr/bin/python3

import aiohttp
import json
import traceback
import asyncio
from datetime import date
from typing import Union
from abc import ABC, abstractmethod
from aiohttp import ClientError, ClientTimeout, ContentTypeError


class ArrApiHandler(ABC):
    """ Base class for usage of the Radarr/Sonarr API """

    # Daily counter for TMDB ID lookups without result, shared between all instances: {(label, tmdbid): (date, count)}
    _not_found_counter = {}

    def __init__(self, logger, token, base_url, label):

        # Init the class
        self.log = logger
        self.token = token
        self.base_url = base_url
        self.label = label
        self.last_error = None

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

        # Reset the last error
        self.last_error = None

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
                                self.last_error = f"HTTP {response.status} {response.reason} (after 3 retries)"
                                await self.log.logger(
                                    f"Not OK response for {self.label} API GET after 3 retries. Last error: {response.status} {response.reason} {await response.text()} - URL: {url}",
                                    True, "error", False
                                )
                                return False

                        # Return false in other cases not OK
                        self.last_error = f"HTTP {response.status} {response.reason}"
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

                self.last_error = f"{type(e).__name__} (after 3 retries)"
                await self.log.logger(
                    f"Error during {self.label} API GET request. Error: {' '.join(map(str, e.args))} - Traceback: {traceback.format_exc()} - URL: {url}",
                    False, "error", False
                )
                return False
            except Exception as e:
                self.last_error = type(e).__name__
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

        # API error (timeout, 4xx, 5xx), details are already logged to file by get()
        if lookup is False:
            await self.log.logger(f"❌ *Error while fetching {self.label} with TMDB ID {tmdbid}.*\nReason: {self.last_error}\nCheck the error log for more information. ❌", False, "error")
            return None

        # API call was OK, but there is no result for this TMDB ID
        if not lookup:
            await self.log_not_found(tmdbid, url_label)
            return None

        # Return the data
        return lookup

    async def log_not_found(self, tmdbid: str, url_label: str) -> None:
        """ Logs a TMDB ID without lookup result, sends a Telegram message only once a day per ID """

        # Set the service name
        service = "Sonarr" if self.label == "serie" else "Radarr"

        # Update the daily counter for this ID
        key = (self.label, str(tmdbid))
        today = date.today()
        day, count = self._not_found_counter.get(key, (today, 0))
        count = count + 1 if day == today else 1
        self._not_found_counter[key] = (today, count)

        # Send Telegram message only the first time today, always log to file with the daily count
        if count == 1:
            await self.log.logger(f"⚠️ *No {self.label} found with TMDB ID {tmdbid}.*\nThe TMDB ID may not exist (anymore) or is not linked in {service}. This message is sent once a day. ⚠️", False, "warning")
        await self.log.logger(f"No {self.label} found with TMDB ID {tmdbid}: {service} API returned an empty result for /{url_label}/lookup?term=tmdb:{tmdbid}. Occurrence {count} today.", False, "warning", False)
