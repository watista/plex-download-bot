#!/usr/bin/python3

import os
from urllib.parse import quote
from src.services.arr import ArrApiHandler


class Sonarr(ArrApiHandler):
    """ Specific class for the Sonarr API """

    def __init__(self, faults):
        super().__init__(faults, os.getenv('SONARR_API'), os.getenv('SONARR_URL'), "sonarr", "series")

    async def lookup_by_name(self, serie_name: str) -> list[dict]:
        """ The series Sonarr finds for a title """
        return await self.get(f"/series/lookup?term={quote(serie_name, safe='')}", action="series search")

    async def queue_download(self, payload: dict) -> dict:
        """ Adds a series to Sonarr, which starts its download: gives back the series as Sonarr has it now, with its
        path """
        return await self.post("/series", payload, action="series request")

    async def scan_missing_media(self, context=None) -> dict:
        """ Starts the search for the missing monitored episodes """
        payload = {"name": "MissingEpisodeSearch", "filterKey": "monitored", "filterValue": "true"}
        return await self.post("/command", payload, action="search for missing episodes")
