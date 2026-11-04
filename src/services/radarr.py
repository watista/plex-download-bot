#!/usr/bin/python3

import os
from urllib.parse import quote
from src.services.arr import ArrApiHandler


class Radarr(ArrApiHandler):
    """ Specific class for the Radarr API """

    def __init__(self, faults):
        super().__init__(faults, os.getenv('RADARR_API'), os.getenv('RADARR_URL'), "radarr", "movie")

    async def lookup_by_name(self, movie_name: str) -> list[dict]:
        """ The movies Radarr finds for a title """
        return await self.get(f"/movie/lookup?term={quote(movie_name, safe='')}", action="movie search")

    async def queue_download(self, payload: dict) -> dict:
        """ Adds a movie to Radarr, which starts its download: gives back the movie as Radarr has it now """
        return await self.post("/movie", payload, action="movie request")

    async def scan_missing_media(self, context=None) -> dict:
        """ Starts the search for the missing monitored movies """
        payload = {"name": "missingMoviesSearch", "filterKey": "monitored", "filterValue": "true"}
        return await self.post("/command", payload, action="search for missing movies")
