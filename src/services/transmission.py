#!/usr/bin/python3

""" The client of Transmission: every request through the requestregel, in 1 attempt """

import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from transmission_rpc import Client, Torrent
from transmission_rpc.error import TransmissionAuthError, TransmissionConnectError, TransmissionTimeoutError

from src.faults import Fault
from src.services.request import Answer, call

if TYPE_CHECKING:
    from src.faults import FaultReporter


class TransmissionService:
    """ The client of Transmission. A request that fails raises its Fault; faults, the meldfunctie, hears of every
    successful answer.

    transmission-rpc is synchronous: while a request lasts, the event loop waits.
    """

    def __init__(self, faults: "FaultReporter"):
        self.faults = faults

    async def check(self) -> None:
        """ Asks Transmission for its session, which says it answers and accepts the user and password """
        await self._request("session check", lambda client: None)

    async def get_active_torrents(self) -> list[Torrent]:
        """ The torrents in Transmission, with their names """
        return await self._request("torrent list", lambda client: client.get_torrents(arguments=["name"]))

    async def _request(self, action: str, ask: Callable[[Client], Any]) -> Any:
        """ A request with transmission-rpc through the requestregel: what ask gives back, or the Fault.

        The client asks Transmission for its session when it is made. The attempt converts what transmission-rpc
        raises: not reaching Transmission to what the requestregel calls unreachable, and a user or password it does
        not accept to its HTTP status. Anything else it raises is a Bug.
        """
        host, port = os.getenv("TRANSMISSION_IP"), os.getenv("TRANSMISSION_PORT")

        async def attempt() -> Answer:
            try:
                client = Client(host=host, port=port, username=os.getenv("TRANSMISSION_USER"),
                                password=os.getenv("TRANSMISSION_PWD"))
                return Answer(200, ask(client))
            except TransmissionTimeoutError as error:
                raise TimeoutError(str(error)) from error
            except TransmissionConnectError as error:
                raise ConnectionError(str(error)) from error
            except TransmissionAuthError as error:
                status = error.original.status_code if error.original is not None else 401
                return Answer(status, reason=error.message)

        try:
            # The url without the user and password, which transmission-rpc puts in its own
            return await call("transmission", action, attempt, self.faults, retries=1, method="POST",
                              url=f"http://{host}:{port}/transmission/rpc")
        except Fault:
            raise
        except Exception as error:
            raise Fault.bug(service="transmission",
                            what=f"Transmission gave an unexpected answer to the {action}") from error
