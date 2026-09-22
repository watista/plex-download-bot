#!/usr/bin/python3

import aiohttp
import json
import os
import traceback
import asyncio
import time
from datetime import date
from typing import Union
from abc import ABC, abstractmethod
from aiohttp import ClientError, ClientTimeout, ContentTypeError


class ArrApiHandler(ABC):
    """ Base class for usage of the Radarr/Sonarr API """

    # Failed TMDB ID lookups in a row, shared between all instances: {(label, tmdbid): {"count": int, "alerted": date}}
    _lookup_failures = {}

    def __init__(self, logger, token, base_url, label):

        # Init the class
        self.log = logger
        self.token = token
        self.base_url = base_url
        self.label = label
        self.last_error = None

        # Amount of failed lookups in a row before a Telegram message is sent.
        # SkyHook hiccups are almost always gone on the next schedule tick.
        try:
            self.failure_threshold = max(1, int(os.getenv("LOOKUP_ALERT_THRESHOLD", "3")))
        except ValueError:
            self.failure_threshold = 3

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
            started = time.monotonic()
            try:
                await self.log.debug_call(self.label, "GET request", url=url, attempt=attempt)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, params=params) as response:

                        # Continue if 2xx
                        if 200 <= response.status < 300:
                            try:
                                data = await response.json()
                            except ContentTypeError:
                                # Some endpoints may return non-JSON on success
                                data = {"raw": await response.text()}

                            await self.log.debug_call(self.label, "GET response", url=url, status=response.status, duration=time.monotonic() - started, response=data)
                            return data

                        # Retry if 5xx
                        if response.status in (500, 502, 503, 504):
                            if attempt < 3:
                                await self.log.debug_call(self.label, "GET retry", url=url, status=response.status, duration=time.monotonic() - started, response=await response.text())
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
                    await self.log.debug_call(self.label, "GET retry", url=url, error=f"{type(e).__name__}: {' '.join(map(str, e.args))}", duration=time.monotonic() - started)
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

        # Reset the last error
        self.last_error = None

        # Make the async request
        for attempt in range(1, 3 + 1):
            started = time.monotonic()
            try:
                await self.log.debug_call(self.label, "POST request", url=url, payload=payload, attempt=attempt)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, params=params, json=payload) as response:
                        # Continue if 2xx
                        if 200 <= response.status < 300:
                            try:
                                data = await response.json()
                            except ContentTypeError:
                                data = {"raw": await response.text()}

                            await self.log.debug_call(self.label, "POST response", url=url, status=response.status, duration=time.monotonic() - started, response=data)
                            return data

                        # Retry if 5xx
                        if response.status in (500, 502, 503, 504) and attempt < 3:
                            await self.log.debug_call(self.label, "POST retry", url=url, status=response.status, duration=time.monotonic() - started, response=await response.text())
                            await asyncio.sleep(3)
                            continue

                        self.last_error = f"HTTP {response.status} {response.reason}"
                        await self.log.logger(
                            f"Not OK response for {self.label} API POST. Error: {response.status} {response.reason} {await response.text()} - URL: {url} - Payload: {payload}",
                            False, "error", False
                        )
                        return False

            except (ClientError, asyncio.TimeoutError) as e:
                if attempt < 3:
                    await self.log.debug_call(self.label, "POST retry", url=url, error=f"{type(e).__name__}: {' '.join(map(str, e.args))}", duration=time.monotonic() - started)
                    await asyncio.sleep(3)
                    continue
                self.last_error = f"{type(e).__name__} (after 3 retries)"
                await self.log.logger(
                    f"Error during {self.label} API POST request. Error: {' '.join(map(str, e.args))} - Traceback: {traceback.format_exc()} - URL: {url} - Payload: {payload}",
                    False, "error", False
                )
                return False
            except Exception as e:
                self.last_error = type(e).__name__
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
            reason = self.last_error if disks is False else "empty response"
            await self.log.logger(f"❌ *Error while fetching {self.label} diskspace information.*\nReason: {reason}\nCheck the error log for more information. ❌", False, "error")
            await self.log.logger(f"Error while fetching {self.label} diskspace information. Reason: {reason} - Request: GET {self.base_url}/diskspace? - Response: {self.log.truncate(disks)}", False, "error", False)
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
            await self.log_lookup_failure(tmdbid, url_label, f"API error: {self.last_error}", lookup)
            return None

        # API call was OK, but there is no result for this TMDB ID
        if not lookup:
            await self.log_lookup_failure(tmdbid, url_label, "API returned an empty result", lookup)
            return None

        # When SkyHook is having a bad day it sometimes answers a tmdb: search with a
        # completely different serie/movie. Acting on that gives wrong notifications,
        # so only accept a result that really is the requested TMDB ID.
        first = lookup[0] if isinstance(lookup, list) else lookup
        returned_id = str(first.get("tmdbId") or "") if isinstance(first, dict) else ""
        if returned_id and returned_id != str(tmdbid):
            await self.log_lookup_failure(tmdbid, url_label, f"API returned a different {self.label}: {first.get('title', 'unknown')} (TMDB ID {returned_id})", lookup)
            return None

        # A good answer ends the failure streak for this ID
        self._lookup_failures.pop((self.label, str(tmdbid)), None)

        # Return the data
        return lookup

    async def log_lookup_failure(self, tmdbid: str, url_label: str, reason: str, response) -> None:
        """ Counts failed lookups in a row, only sends a Telegram message from the threshold on """

        # Set the service name
        service = "Sonarr" if self.label == "serie" else "Radarr"

        # Count how many times in a row this ID failed
        key = (self.label, str(tmdbid))
        state = self._lookup_failures.setdefault(key, {"count": 0, "alerted": None})
        state["count"] += 1
        count = state["count"]

        # Always write the details to the log file
        await self.log.logger(f"Lookup failed for {self.label} with TMDB ID {tmdbid}: {reason}. Failure {count} in a row, alerting from {self.failure_threshold}. Request: GET {self.base_url}/{url_label}/lookup?term=tmdb:{tmdbid} - Response: {self.log.truncate(response)}", False, "warning", False)

        # Below the threshold it is almost always a temporary SkyHook/TMDB hiccup, stay silent
        if count < self.failure_threshold:
            return

        # Past the threshold, send at most one Telegram message a day per ID
        today = date.today()
        if state["alerted"] == today:
            return
        state["alerted"] = today

        await self.log.logger(f"⚠️ *No {self.label} found with TMDB ID {tmdbid}.*\n{count} lookups in a row failed: {reason}.\nThe TMDB ID may not exist (anymore) or is not linked in {service}. This message is sent once a day. ⚠️", False, "warning")
