#!/usr/bin/python3

import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from transmission_rpc.error import (TransmissionAuthError, TransmissionConnectError, TransmissionError,
                                    TransmissionTimeoutError)

from src.faults import Fault, FaultKind
from src.log import setup_logging
from src.services.transmission import TransmissionService
from test_interaction import FakeFaults
from test_log import DEBUG, MAIN, LogFolder


class TransmissionTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ The client of Transmission with a fake transmission-rpc Client and a fake meldfunctie """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "DEBUG", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:30:00+01:00"))
        self.enterContext(patch.dict(os.environ, {"TRANSMISSION_IP": "transmission.example.com",
                                                  "TRANSMISSION_PORT": "9091", "TRANSMISSION_USER": "wouter"}))
        self.client = self.enterContext(patch("src.services.transmission.Client"))
        self.faults = FakeFaults()
        self.transmission = TransmissionService(self.faults)

    def fails_with(self, error: Exception) -> None:
        """ transmission-rpc raises this exception when it makes its client, which asks for the session """
        self.client.side_effect = error

    async def failed_check(self) -> Fault:
        with self.assertRaises(Fault) as caught:
            await self.transmission.check()
        return caught.exception

    async def test_a_check_of_a_transmission_that_answers(self):
        await self.transmission.check()

        self.client.assert_called_once_with(host="transmission.example.com", port="9091", username="wouter",
                                            password=os.environ["TRANSMISSION_PWD"])
        self.assertEqual(self.faults.oks, ["transmission"])

    async def test_transmission_that_cannot_be_reached_is_a_storing_after_one_attempt(self):
        refused = TransmissionConnectError("can't connect to transmission daemon: Connection refused")
        self.fails_with(refused)

        fault = await self.failed_check()

        self.assertEqual((fault.kind, fault.service, fault.what),
                         (FaultKind.DISRUPTION, "transmission", "Transmission is not responding"))
        self.assertIs(fault.__cause__.__cause__, refused)
        self.assertEqual(str(fault.__cause__), "can't connect to transmission daemon: Connection refused")
        self.assertEqual(self.client.call_count, 1)
        self.assertEqual(self.faults.oks, [])

    async def test_a_timeout_is_a_storing_too(self):
        self.fails_with(TransmissionTimeoutError("timeout when connection to transmission daemon"))

        fault = await self.failed_check()

        self.assertEqual(fault.kind, FaultKind.DISRUPTION)
        self.assertIsInstance(fault.__cause__, TimeoutError)

    async def test_a_user_and_password_that_transmission_does_not_accept_are_an_inrichtingsfout(self):
        answer = requests.Response()
        answer.status_code = 401
        self.fails_with(TransmissionAuthError("transmission daemon require auth", original=answer))

        fault = await self.failed_check()

        self.assertEqual((fault.kind, fault.service, fault.check, fault.item, fault.http_status, fault.what),
                         (FaultKind.SETUP, "transmission", "setting", "TRANSMISSION_USER and TRANSMISSION_PWD", 401,
                          "Transmission does not accept TRANSMISSION_USER and TRANSMISSION_PWD"))

    async def test_a_check_that_passes_fixes_the_user_and_password(self):
        await self.transmission.check()

        [fix] = self.faults.fixes
        self.assertEqual((fix.service, fix.check, fix.item, fix.msg),
                         ("transmission", "setting", "TRANSMISSION_USER and TRANSMISSION_PWD",
                          "Transmission accepts TRANSMISSION_USER and TRANSMISSION_PWD again"))

    async def test_another_error_of_transmission_rpc_is_a_bug(self):
        unexpected = TransmissionError('Query failed with result "method name not recognized".')
        self.fails_with(unexpected)

        fault = await self.failed_check()

        self.assertEqual((fault.kind, fault.service, fault.what),
                         (FaultKind.BUG, "transmission", "Transmission gave an unexpected answer to the session check"))
        self.assertIs(fault.__cause__, unexpected)

    async def test_the_client_writes_no_line_of_its_own(self):
        # The Fault is the line, written by whoever reports it: the wrapper of the job, or the caller that goes on
        self.fails_with(TransmissionConnectError("can't connect to transmission daemon"))

        await self.failed_check()

        self.assertEqual(self.read(MAIN), [])
        [http_call] = [line for line in self.read(DEBUG) if line.get("event") == "http_call"]
        self.assertEqual(http_call["url"], "http://transmission.example.com:9091/transmission/rpc")
        self.assertEqual(http_call["exc_type"], "ConnectionError")

    async def test_the_active_torrents(self):
        torrents = [SimpleNamespace(name="Dune.2021.2160p")]
        self.client.return_value = MagicMock(get_torrents=MagicMock(return_value=torrents))

        self.assertEqual(await self.transmission.get_active_torrents(), torrents)
        self.client.return_value.get_torrents.assert_called_once_with(arguments=["name"])
        self.assertEqual(self.faults.oks, ["transmission"])

    async def test_the_active_torrents_of_a_transmission_that_cannot_be_reached(self):
        self.fails_with(TransmissionConnectError("can't connect to transmission daemon"))

        with self.assertRaises(Fault) as caught:
            await self.transmission.get_active_torrents()

        self.assertEqual((caught.exception.kind, caught.exception.service), (FaultKind.DISRUPTION, "transmission"))


if __name__ == "__main__":
    unittest.main()
