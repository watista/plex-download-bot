#!/usr/bin/python3

import os
import time
import traceback
from typing import Optional

from plexapi.server import PlexServer


class Plex:
    """Wraps PlexServer with lazy connect so the bot can start if Plex is temporarily down."""

    _RETRY_AFTER_SEC = 300.0

    def __init__(self, logger):

        self.log = logger
        self.plex_server_id = os.getenv("PLEX_ID")
        self._plex_url = os.getenv("PLEX_URL")
        self._plex_token = os.getenv("PLEX_API")
        self._plex: Optional[PlexServer] = None
        self._next_connect_attempt_monotonic: float = 0.0

    async def _get_server(self) -> Optional[PlexServer]:
        now = time.monotonic()
        if self._plex is not None:
            return self._plex
        if now < self._next_connect_attempt_monotonic:
            return None
        if not self._plex_url or not self._plex_token:
            await self.log.logger(
                "❌ *Plęx URL or API token missing in environment* ❌",
                False,
                "error",
                False,
            )
            self._next_connect_attempt_monotonic = now + self._RETRY_AFTER_SEC
            return None
        try:
            # Shorter than default 30s so a dead host does not block for ages on each retry window.
            self._plex = PlexServer(self._plex_url, self._plex_token, timeout=10)
            return self._plex
        except Exception as e:
            await self.log.logger(
                f"⚠️ *Could not connect to Plęx* (bot keeps running). Error: {e} ⚠️",
                False,
                "warning",
                False,
            )
            await self.log.logger(
                f"Plex connect traceback:\n{traceback.format_exc()}",
                False,
                "debug",
                False,
            )
            self._plex = None
            self._next_connect_attempt_monotonic = now + self._RETRY_AFTER_SEC
            return None

    async def get_media_url(self, media_data: dict, media_type: str) -> Optional[str]:
        """Create's a Plex link to the media"""

        plex = await self._get_server()
        if plex is None:
            return None

        # Set media type
        section = "Movies" if media_type == "film" else "TV Shows"

        # Check if media_data is a list or dict
        if isinstance(media_data, list):
            media_data = next(iter(media_data), {})

        # Ensure title exists
        title = media_data.get("title", "").strip()
        if not title:
            await self.log.logger(
                "❌ *Error while creating a Plęx link* ❌\n\nNo title is present in the JSON. Check the error log for more information.",
                False,
                "error",
            )
            await self.log.logger(f"Full JSON output: {media_data}", False, "error", False)
            return None

        # Get movie by name from Plex
        try:
            media = plex.library.section(section).search(title)
        except Exception as e:
            await self.log.logger(
                f"❌ *Error while querying Plęx library* ❌\n\n{e}",
                False,
                "error",
                False,
            )
            await self.log.logger(f"Traceback: {traceback.format_exc()}", False, "error", False)
            return None

        if not media:
            await self.log.logger(f"⚠️ *No Plęx match found for '{title}'* ⚠️", False, "warning")
            return None

        # Create URL's if there is a match, otherwise throw error and return none
        try:
            return (
                f"https://app.plex.tv/desktop/#!/server/{self.plex_server_id}/details?"
                f"key=%2Flibrary%2Fmetadata%2F{media[0].ratingKey}"
            )
        except (IndexError, KeyError):
            await self.log.logger(
                f"❌ *No valid media found in Plęx for '{title}'* ❌\n\nCheck the error log for more information.",
                False,
                "error",
            )
        except Exception as e:
            await self.log.logger(
                "❌ *Error while creating a Plęx link* ❌\n\nCheck the error log for more information.",
                False,
                "error",
            )
            await self.log.logger(f"Unexpected error while creating Plęx link: {e}", False, "error")
            await self.log.logger(f"Traceback: {traceback.format_exc()}", False, "error", False)
            await self.log.logger(f"Full JSON output: {media_data}", False, "error", False)

        return None
