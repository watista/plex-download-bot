#!/usr/bin/python3

import os
import traceback
from typing import Any, Tuple

from transmission_rpc import Client

# Used to detect down -> up
_last_transmission_up: bool | None = None


class TransmissionService:
    """
    Lightweight wrapper around transmission-rpc that:
    - treats connection issues as "down" (no exceptions leak by default)
    """

    def __init__(self, logger):
        self.log = logger

    def _client(self) -> Client:
        return Client(
            host=os.getenv("TRANSMISSION_IP"),
            port=os.getenv("TRANSMISSION_PORT"),
            username=os.getenv("TRANSMISSION_USER"),
            password=os.getenv("TRANSMISSION_PWD"),
        )

    async def is_available(self) -> bool:
        try:
            # Any RPC call is enough to validate connectivity/auth.
            c = self._client()
            c.get_session()
            return True
        except Exception:
            return False

    async def get_active_torrents(self) -> Tuple[bool, list[Any]]:
        """
        Returns: (is_up, torrents)
        torrents will be [] when Transmission is down.
        """
        try:
            c = self._client()
            torrents = c.get_torrents(arguments=["name"])
            return True, torrents
        except Exception as e:
            await self.log.logger(
                f"Transmission is not reachable. Error: {' '.join(map(str, e.args))}",
                False,
                "warning",
                False,
            )
            await self.log.logger(
                f"Transmission connection traceback:\n{traceback.format_exc()}",
                False,
                "debug",
                False,
            )
            return False, []


async def check_transmission_and_trigger_scans(
    *,
    logger,
    radarr=None,
    sonarr=None,
) -> bool:
    """
    Checks Transmission health (in-memory previous state only).

    If Transmission recovered (down -> up) and radarr/sonarr are provided,
    it triggers missing media scans immediately.

    Returns: True if Transmission is currently reachable, else False.
    """
    global _last_transmission_up

    svc = TransmissionService(logger)
    is_up = await svc.is_available()

    prev_up = _last_transmission_up
    recovered = prev_up is False and is_up
    _last_transmission_up = is_up

    if recovered:
        await logger.logger(
            "Transmission recovered (down -> up). Triggering Arr missing-media scans.",
            False,
            "info",
            False,
        )
        try:
            if sonarr is not None:
                await sonarr.scan_missing_media()
            if radarr is not None:
                await radarr.scan_missing_media()
        except Exception as e:
            await logger.logger(
                f"Failed triggering Arr scans after Transmission recovery. Error: {e}",
                False,
                "warning",
                False,
            )

    return bool(is_up)
