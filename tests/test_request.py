#!/usr/bin/python3

import os
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import ClientConnectionError

from src.faults import Fault, FaultKind
from src.log import setup_logging
from src.services.request import RETRY_WAIT, Answer, call
from test_interaction import FakeFaults
from test_log import DEBUG, MAIN, LogFolder


URL = "https://radarr.example.com/api/v3/movie"
PAYLOAD = {"tmdbId": 693134, "monitored": True}

# What Radarr answers to a movie that is already in Radarr
ALREADY_ADDED = [{"propertyName": "TmdbId", "errorMessage": "This movie has already been added",
                  "attemptedValue": 693134}]


class CallTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ The requestregel with an attempt that answers what the test says, and a fake meldfunctie """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "DEBUG", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))
        self.faults = FakeFaults()
        self.sleep = AsyncMock()
        self.enterContext(patch("src.services.request.asyncio.sleep", self.sleep))

        # Every attempt takes no time, unless a test says otherwise
        self.clock = self.enterContext(patch("src.services.request.monotonic", return_value=100.0))

    @staticmethod
    def attempt(*answers: Answer | Exception) -> AsyncMock:
        """ An attempt that gives these answers or raises these exceptions, one per attempt """
        return AsyncMock(side_effect=list(answers))

    async def call(self, attempt: AsyncMock, **kwargs):
        """ A movie request to Radarr through the requestregel """
        return await call("radarr", "movie request", attempt, self.faults, method="POST", url=URL, request=PAYLOAD,
                          **kwargs)

    def http_calls(self) -> list[dict]:
        return [line for line in self.read(DEBUG) if line.get("event") == "http_call"]

    async def test_three_503s_give_one_storing_after_the_last_attempt(self):
        attempt = self.attempt(*[Answer(503, "Service Unavailable", "Service Unavailable")] * 3)

        with self.assertRaises(Fault) as caught:
            await self.call(attempt)

        fault = caught.exception
        self.assertEqual((fault.kind, fault.service, fault.what, fault.reason, fault.http_status),
                         (FaultKind.DISRUPTION, "radarr", "Radarr is not responding", "Service Unavailable", 503))
        self.assertEqual(attempt.await_count, 3)
        self.assertEqual([c.args for c in self.sleep.await_args_list], [(RETRY_WAIT,), (RETRY_WAIT,)])
        self.assertEqual(self.faults.oks, [])

    async def test_a_storing_that_is_over_at_the_next_attempt_is_no_fault(self):
        attempt = self.attempt(Answer(502, None, "Bad Gateway"), Answer(201, {"id": 1}))

        self.assertEqual(await self.call(attempt), {"id": 1})
        self.assertEqual(self.faults.oks, ["radarr"])

    async def test_a_service_that_cannot_be_reached_is_a_storing_from_the_exception(self):
        for error in (ClientConnectionError("Cannot connect to host radarr.example.com:443"), TimeoutError()):
            with self.subTest(error=type(error).__name__):
                attempt = self.attempt(error, error, error)

                with self.assertRaises(Fault) as caught:
                    await self.call(attempt)

                fault = caught.exception
                self.assertEqual((fault.kind, fault.what, fault.http_status),
                                 (FaultKind.DISRUPTION, "Radarr is not responding", None))
                self.assertIs(fault.__cause__, error)
                self.assertEqual(attempt.await_count, 3)

    async def test_a_400_is_a_bug_with_the_reason_and_the_status(self):
        attempt = self.attempt(Answer(400, ALREADY_ADDED, "This movie has already been added"))

        with self.assertRaises(Fault) as caught:
            await self.call(attempt)

        fault = caught.exception
        self.assertEqual((fault.kind, fault.service, fault.what, fault.reason, fault.http_status),
                         (FaultKind.BUG, "radarr", "Radarr refused the movie request",
                          "This movie has already been added", 400))
        self.assertEqual(attempt.await_count, 1)
        self.sleep.assert_not_awaited()

    async def test_the_reason_has_at_most_300_characters(self):
        attempt = self.attempt(Answer(400, None, "x" * 1000))

        with self.assertRaises(Fault) as caught:
            await self.call(attempt)

        self.assertEqual(len(caught.exception.reason), 300)
        self.assertTrue(caught.exception.reason.endswith("…"))

    async def test_401_and_403_are_an_inrichtingsfout_of_the_api_key(self):
        for status in (401, 403):
            with self.subTest(status=status):
                attempt = self.attempt(Answer(status, None, "Unauthorized"))

                with self.assertRaises(Fault) as caught:
                    await self.call(attempt)

                fault = caught.exception
                self.assertEqual((fault.kind, fault.check, fault.item, fault.http_status, fault.reason),
                                 (FaultKind.SETUP, "setting", "RADARR_API", status, "Unauthorized"))
                self.assertEqual(fault.what, "Radarr does not accept RADARR_API")
                self.assertEqual(attempt.await_count, 1)

    async def test_ok_once_after_a_successful_answer(self):
        attempt = self.attempt(Answer(200, [{"title": "Dune"}]))

        self.assertEqual(await self.call(attempt), [{"title": "Dune"}])
        self.assertEqual(self.faults.oks, ["radarr"])

        # The API key passed its check as well
        [fix] = self.faults.fixes
        self.assertEqual((fix.service, fix.check, fix.item, fix.msg),
                         ("radarr", "setting", "RADARR_API", "Radarr accepts RADARR_API again"))

    async def test_every_attempt_gets_an_http_call(self):
        attempt = self.attempt(ClientConnectionError("Connection reset by peer"), Answer(503, "down", "down"),
                               Answer(201, {"id": 1}))

        await self.call(attempt)

        calls = self.http_calls()
        self.assertEqual([line["msg"] for line in calls], [
            f"radarr movie request: POST {URL}: ClientConnectionError: Connection reset by peer in 0 ms, "
            "attempt 1 of 3",
            f"radarr movie request: POST {URL}: HTTP 503 in 0 ms, attempt 2 of 3",
            f"radarr movie request: POST {URL}: HTTP 201 in 0 ms, attempt 3 of 3",
        ])
        last = calls[-1]
        self.assertEqual((last["service"], last["method"], last["url"], last["http_status"], last["duration_ms"]),
                         ("radarr", "POST", URL, 201, 0))
        self.assertEqual((last["request"], last["response"]), ('{"tmdbId": 693134, "monitored": true}', '{"id": 1}'))
        self.assertEqual(calls[0]["exc_type"], "ClientConnectionError")
        self.assertNotIn("http_status", calls[0])

        # On DEBUG only
        self.assertEqual([line for line in self.read(MAIN) if line.get("event") == "http_call"], [])

    async def test_the_duration_of_an_attempt(self):
        self.clock.side_effect = [10.0, 10.3204]

        await self.call(self.attempt(Answer(200, [])))

        [line] = self.http_calls()
        self.assertEqual(line["duration_ms"], 320)
        self.assertIn("HTTP 200 in 320 ms", line["msg"])

    async def test_bodies_in_an_http_call_are_cut_at_log_max_body(self):
        attempt = self.attempt(Answer(200, [{"title": "Dune", "year": 2021}]))

        with patch.dict(os.environ, {"LOG_MAX_BODY": "20"}):
            await self.call(attempt)

        [line] = self.http_calls()
        self.assertEqual(line["response"], '[{"title": "Dune", "... [truncated, 33 chars total]')

    async def test_an_exception_it_does_not_know_falls_through_after_its_http_call(self):
        error = ValueError("Expecting value: line 1 column 1 (char 0)")
        attempt = self.attempt(error)

        with self.assertRaises(ValueError) as caught:
            await self.call(attempt)

        self.assertIs(caught.exception, error)
        self.assertEqual(attempt.await_count, 1)
        [line] = self.http_calls()
        self.assertEqual(line["exc_type"], "ValueError")

    async def test_a_service_with_one_attempt_is_not_retried(self):
        attempt = self.attempt(Answer(503, None, "down"))

        with self.assertRaises(Fault):
            await call("plex", "library search", attempt, self.faults, retries=1)

        self.assertEqual(attempt.await_count, 1)
        self.sleep.assert_not_awaited()

        # Without a method and URL, the line says what the request was for
        [line] = self.http_calls()
        self.assertEqual(line["msg"], "plex library search: HTTP 503 in 0 ms, attempt 1 of 1")


if __name__ == "__main__":
    unittest.main()
