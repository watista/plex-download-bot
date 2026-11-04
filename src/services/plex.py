#!/usr/bin/python3

""" The client of Plex: the link to a media item in Plex, every request through the requestregel in 1 attempt """

import os
import re
from collections.abc import Callable
from time import monotonic
from typing import TYPE_CHECKING, Any

import requests
from plexapi.exceptions import PlexApiException
from plexapi.server import PlexServer

from src.faults import Fault, FaultKind, service_name
from src.log import get_logger
from src.services.request import Answer, call

if TYPE_CHECKING:
    from src.faults import FaultReporter


log = get_logger(__name__)

# The seconds after a connection that failed before a link tries to connect again. plexapi is synchronous, so every
# try at a Plex that does not answer holds up the event loop for as long as the timeout.
RETRY_AFTER = 300.0

# The seconds a request to Plex may take, shorter than the 30 of plexapi
TIMEOUT = 10

# The settings that the connection needs: the URL of Plex and its token
SETTINGS = ("PLEX_URL", "PLEX_API")

# How plexapi starts the text of an HTTP error: the status and its name, like "(503) service_unavailable;"
HTTP_ERROR = re.compile(r"\((\d{3})\) (\w+);")


class Plex:
    """ The client of Plex. It connects at the first link, so the bot starts while Plex is down, and after a
    connection that failed it waits RETRY_AFTER before the next try. A request that fails raises its Fault; faults,
    the meldfunctie, hears of every successful answer and every check that passes.
    """

    def __init__(self, faults: "FaultReporter"):
        self.faults = faults
        self.plex_server_id = os.getenv("PLEX_ID")
        self._url = os.getenv("PLEX_URL")
        self._token = os.getenv("PLEX_API")
        self._server: PlexServer | None = None
        self._next_connect = 0.0

    async def link(self, media: dict | list, media_type: str) -> str | None:
        """ The link to a media item of Radarr or Sonarr in Plex, for an answer that also goes out without it.
        media_type is film or serie; of a list of lookup results it is the first.

        None when Plex has no match for the title, a line on WARNING, or while the client waits to connect again. A
        Fout is reported here and not raised, as the answer goes on without the link.
        """
        try:
            return await self._link(next(iter(media), {}) if isinstance(media, list) else media, media_type)
        except Fault as fault:
            await self.faults.report(fault, continued="sent the answer without a Plex link")
            return None

    async def _link(self, media: dict, media_type: str) -> str | None:
        """ The link to the media in Plex, None without a match or a connection; raises the Fault of what failed """
        section, service = ("Movies", "radarr") if media_type == "film" else ("TV Shows", "sonarr")
        title, tmdb_id, name = (media.get("title") or "").strip(), media.get("tmdbId"), service_name(service)
        if not title:
            raise Fault.setup(service=service, what=f"{name} gives no title for tmdb {tmdb_id}", check="media_title",
                              item=tmdb_id)
        await self.faults.fixed(service, "media_title", tmdb_id, msg=f"{name} gives a title for tmdb {tmdb_id} again")

        server = await self._connect()
        if server is None:
            return None
        found = await self._request("library search", lambda: server.library.section(section).search(title),
                                    request={"section": section, "title": title})
        if not found:
            log.warning(f"no match in Plex for '{title}' in {section}", media=media)
            return None
        return (f"https://app.plex.tv/desktop/#!/server/{self.plex_server_id}/details?"
                f"key=%2Flibrary%2Fmetadata%2F{found[0].ratingKey}")

    async def _connect(self) -> PlexServer | None:
        """ The connection to Plex, made at the first link; None while the client waits to connect again.

        A missing setting is an Inrichtingsfout of that setting. So is a URL that does not lead to Plex: at the
        connection the bot only asks for the root of Plex, so whatever plexapi makes a Bug of here (a 404, an answer
        that is no XML of Plex, a URL that requests cannot use) says the URL is wrong.
        """
        if self._server is not None:
            return self._server
        for setting, value in zip(SETTINGS, (self._url, self._token)):
            if not value:
                raise Fault.setup(service="plex", what=f"{setting} is not set", check="setting", item=setting)
        if monotonic() < self._next_connect:
            log.debug(f"no Plex link: the last connection failed less than {RETRY_AFTER / 60:g} minutes ago")
            return None

        try:
            self._server = await self._request("connection",
                                               lambda: PlexServer(self._url, self._token, timeout=TIMEOUT))
        except Fault as fault:
            self._next_connect = monotonic() + RETRY_AFTER
            if fault.kind != FaultKind.BUG:
                raise
            raise Fault.setup(service="plex", what="PLEX_URL does not lead to Plex", check="setting", item="PLEX_URL",
                              reason=fault.reason, http_status=fault.http_status) from fault.__cause__
        await self.faults.fixed("plex", "setting", "PLEX_URL", msg="Plex answers at PLEX_URL again")
        return self._server

    async def _request(self, action: str, ask: Callable[[], Any], **fields) -> Any:
        """ A request with plexapi through the requestregel: what ask gives back, or the Fault.

        The attempt converts what plexapi raises: not reaching Plex to what the requestregel calls unreachable, and
        an HTTP error to its status. Anything else it raises is a Bug. fields go to the http_call.
        """

        async def attempt() -> Answer:
            try:
                return Answer(200, ask())
            except requests.exceptions.Timeout as error:
                raise TimeoutError(str(error)) from error
            except requests.exceptions.ConnectionError as error:
                raise ConnectionError(str(error)) from error
            except PlexApiException as error:
                http_error = HTTP_ERROR.match(str(error))
                if http_error is None:
                    raise
                return Answer(int(http_error[1]), reason=http_error[2].replace("_", " "))

        try:
            # plexapi sends the token in a header, so the URL is without it
            return await call("plex", action, attempt, self.faults, retries=1, method="GET", url=self._url, **fields)
        except Fault:
            raise
        except Exception as error:
            raise Fault.bug(service="plex", what=f"Plex gave an unexpected answer to the {action}") from error
