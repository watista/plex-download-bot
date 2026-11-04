#!/usr/bin/python3

import os
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import aiohttp
from aiohttp import ClientTimeout, ContentTypeError

from src.faults import Fault, service_name
from src.services.request import Answer, call

if TYPE_CHECKING:
    from src.faults import FaultReporter


# The longest a request to Radarr or Sonarr may take
TIMEOUT = ClientTimeout(total=30)


class ArrApiHandler(ABC):
    """ Base class for usage of the Radarr/Sonarr API, every request through the requestregel.

    service is radarr or sonarr, media_type how its API calls its media: movie or series. A request that fails raises
    its Fault; faults, the meldfunctie, hears of every successful answer and every check that passes.
    """

    def __init__(self, faults: "FaultReporter", token: str, base_url: str, service: str, media_type: str):
        self.faults = faults
        self.token = token
        self.base_url = base_url
        self.service = service
        self.media_type = media_type

    @abstractmethod
    async def lookup_by_name(self, media_name: str) -> list[dict]:
        """ Abstract method that does a media lookup in the subclass """
        pass

    @abstractmethod
    async def queue_download(self, payload: dict) -> dict:
        """ Abstract method that starts a download in the subclass """
        pass

    @abstractmethod
    async def scan_missing_media(self) -> dict:
        """ Abstract method that scans for missing monitored media in the subclass """
        pass

    async def get(self, path: str, *, action: str) -> Any:
        """ A GET request; action says what it is for, like "movie lookup" """
        return await self._request("GET", path, action)

    async def post(self, path: str, payload: dict, *, action: str) -> Any:
        """ A POST request with this JSON; action says what it is for, like "movie request" """
        return await self._request("POST", path, action, payload)

    async def _request(self, method: str, path: str, action: str, payload: dict | None = None) -> Any:
        """ A request through the requestregel, which gives back the body of the answer or raises its Fault """
        url = f"{self.base_url}{path}"

        async def attempt() -> Answer:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                # The key as a parameter, so the url of the http_call does not have it
                async with session.request(method, url, params={"apikey": self.token}, json=payload) as response:
                    try:
                        body = await response.json()
                    except ContentTypeError:
                        body = await response.text()
                    return Answer(response.status, body, None if response.ok else _reason(body, response.reason))

        return await call(self.service, action, attempt, self.faults, method=method, url=url, request=payload)

    async def get_disk_space(self) -> list[dict]:
        """ The disks Radarr or Sonarr sees, each with its path and freeSpace """
        return await self.get("/diskspace", action="disk space check")

    async def lookup_by_tmdbid(self, tmdbid: str | int) -> dict:
        """ The movie or series with this TMDB ID.

        A lookup that finds nothing is an Inrichtingsfout (tmdb_lookup). So is one that finds another movie or
        series: when SkyHook is having a bad day, it sometimes answers a tmdb: search with a completely different
        one, and acting on that gives wrong Gebruikersberichten.
        """
        found = await self.get(f"/{self.media_type}/lookup?term=tmdb:{tmdbid}", action=f"{self.media_type} lookup")
        name = service_name(self.service)
        first = (found if isinstance(found, list) else [found])[0] if found else None
        if not first:
            raise Fault.setup(service=self.service, what=f"{name} finds nothing for tmdb {tmdbid}", check="tmdb_lookup",
                              item=tmdbid)
        if first.get("tmdbId") and str(first["tmdbId"]) != str(tmdbid):
            raise Fault.setup(service=self.service, what=f"{name} finds another {self.media_type} for tmdb {tmdbid}",
                              check="tmdb_lookup", item=tmdbid,
                              details={"title": first.get("title"), "tmdbId": first["tmdbId"]})
        await self.faults.fixed(self.service, "tmdb_lookup", tmdbid,
                                msg=f"{name} finds {first.get('title')} for tmdb {tmdbid} again")
        return first


def _reason(body: Any, http_reason: str | None) -> str | None:
    """ Why Radarr or Sonarr did not answer successfully: its validation errors, its message, its text, or else the
    reason of the HTTP status. A page of a proxy in front of it is no reason. """
    if isinstance(body, list):
        errors = [item["errorMessage"] for item in body if isinstance(item, dict) and item.get("errorMessage")]
        if errors:
            return "; ".join(errors)
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])
    if isinstance(body, str) and body.strip() and not body.lstrip().startswith("<"):
        return body.strip()
    return http_reason


# Per service: the setting with its URL, the page of a media item in its web interface, and the fields of the item
# that name it there, the first one there is. Radarr's titleSlug is the tmdbId.
PAGES = {"radarr": ("RADARR_URL", "movie", ("titleSlug", "tmdbId")),
         "sonarr": ("SONARR_URL", "series", ("titleSlug",))}


def media_link(service: str, media: dict) -> str | None:
    """ The link to a media item in the web interface of Radarr or Sonarr, at the URL of the API without /api/v3.

    None for another service, an item without the field that names it, or one that is not in Radarr or Sonarr: a
    lookup also finds what is not in its library yet, without an id there.
    """
    if service not in PAGES or not media.get("id"):
        return None
    setting, page, fields = PAGES[service]
    slug = next((media[field] for field in fields if media.get(field)), None)
    url = os.getenv(setting)
    if not slug or not url:
        return None
    base = re.sub(r"/api/v\d+$", "", url.rstrip("/"))
    return f"{base}/{page}/{quote(str(slug), safe='')}"
