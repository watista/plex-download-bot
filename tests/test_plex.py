#!/usr/bin/python3

import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from xml.etree.ElementTree import ParseError

import requests
from plexapi.exceptions import BadRequest, NotFound, Unauthorized

from src.faults import FaultKind
from src.log import setup_logging
from src.services.plex import RETRY_AFTER, Plex
from test_interaction import FakeFaults
from test_log import MAIN, LogFolder


URL = "http://plex.example.com:32400"

# A movie as Radarr has it, and as Plex has it
DUNE = {"title": "Dune", "year": 2021, "tmdbId": 438631}
DUNE_IN_PLEX = SimpleNamespace(title="Dune", ratingKey=4242)

# The link to Dune in Plex
LINK = "https://app.plex.tv/desktop/#!/server/server-id/details?key=%2Flibrary%2Fmetadata%2F4242"

# What plexapi raises when it cannot reach Plex
REFUSED = requests.exceptions.ConnectionError(
    "HTTPConnectionPool(host='plex.example.com', port=32400): Max retries exceeded with url: / "
    "(Caused by NewConnectionError('Failed to establish a new connection: [Errno 111] Connection refused'))")


class PlexTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ The client of Plex with a fake PlexServer and a fake meldfunctie. Plex has Dune in its library Movies. """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:30:00+01:00"))
        self.enterContext(patch.dict(os.environ, {"PLEX_URL": URL, "PLEX_ID": "server-id"}))
        self.server = MagicMock()
        self.server.library.section.return_value.search.return_value = [DUNE_IN_PLEX]
        self.plex_server = self.enterContext(patch("src.services.plex.PlexServer", return_value=self.server))
        self.clock = self.enterContext(patch("src.services.plex.monotonic", return_value=1000.0))
        self.faults = FakeFaults()

    def plex(self) -> Plex:
        """ The client, which reads its settings when it is made """
        return Plex(self.faults)

    async def test_a_link_to_the_media_in_plex(self):
        self.assertEqual(await self.plex().link(DUNE, "film"), LINK)

        self.plex_server.assert_called_once_with(URL, os.environ["PLEX_API"], timeout=10)
        self.server.library.section.assert_called_once_with("Movies")
        self.server.library.section.return_value.search.assert_called_once_with("Dune")
        self.assertEqual(self.faults.reports, [])

    async def test_a_series_is_searched_for_in_tv_shows(self):
        await self.plex().link({"title": "Carrie", "tmdbId": 1399}, "serie")

        self.server.library.section.assert_called_once_with("TV Shows")

    async def test_the_first_link_connects_and_the_next_ones_use_that_connection(self):
        plex = self.plex()

        await plex.link(DUNE, "film")
        await plex.link(DUNE, "film")

        self.plex_server.assert_called_once()
        # The connection and two searches, each a successful answer of Plex
        self.assertEqual(self.faults.oks, ["plex", "plex", "plex"])

    async def test_a_link_passes_the_checks_of_the_settings_and_the_title(self):
        await self.plex().link(DUNE, "film")

        self.assertEqual({(fix.service, fix.check, fix.item, fix.msg) for fix in self.faults.fixes}, {
            ("plex", "setting", "PLEX_URL", "Plex answers at PLEX_URL again"),
            ("plex", "setting", "PLEX_API", "Plex accepts PLEX_API again"),
            ("radarr", "media_title", 438631, "Radarr gives a title for tmdb 438631 again"),
        })

    async def test_plex_that_cannot_be_reached_is_one_storing_and_the_answer_goes_on_without_a_link(self):
        self.plex_server.side_effect = REFUSED

        self.assertIsNone(await self.plex().link(DUNE, "film"))

        [report] = self.faults.reports
        fault = report.fault
        self.assertEqual((fault.kind, fault.service, fault.what),
                         (FaultKind.DISRUPTION, "plex", "Plex is not responding"))
        self.assertIs(fault.__cause__.__cause__, REFUSED)
        self.assertEqual((report.continued, report.user_told), ("sent the answer without a Plex link", False))
        # The client writes no line of its own: the line of the Fout is that of the report
        self.assertEqual(self.read(MAIN), [])

    async def test_a_timeout_is_a_storing_too(self):
        self.plex_server.side_effect = requests.exceptions.ConnectTimeout("Connection to plex timed out")

        await self.plex().link(DUNE, "film")

        [report] = self.faults.reports
        self.assertEqual(report.fault.kind, FaultKind.DISRUPTION)
        self.assertIsInstance(report.fault.__cause__, TimeoutError)

    async def test_after_a_connection_that_failed_it_waits_before_it_tries_again(self):
        self.plex_server.side_effect = REFUSED
        plex = self.plex()
        await plex.link(DUNE, "film")

        # Within the wait: no link, and no request, so no attempt of the Storing either
        self.clock.return_value = 1000.0 + RETRY_AFTER - 1
        self.assertIsNone(await plex.link(DUNE, "film"))
        self.assertEqual(self.plex_server.call_count, 1)
        self.assertEqual(len(self.faults.reports), 1)

        # After the wait it connects again
        self.plex_server.side_effect = None
        self.clock.return_value = 1000.0 + RETRY_AFTER
        self.assertEqual(await plex.link(DUNE, "film"), LINK)
        self.assertEqual(self.plex_server.call_count, 2)

    async def test_a_library_that_gives_a_server_error_is_a_storing(self):
        self.server.library.section.return_value.search.side_effect = BadRequest(
            f"(503) service_unavailable; {URL}/library/sections/1/all?title=Dune <html>Service Unavailable</html>")

        await self.plex().link(DUNE, "film")

        [report] = self.faults.reports
        fault = report.fault
        self.assertEqual((fault.kind, fault.service, fault.what, fault.http_status, fault.reason),
                         (FaultKind.DISRUPTION, "plex", "Plex is not responding", 503, "service unavailable"))

    async def test_a_missing_setting_is_an_inrichtingsfout_without_a_request(self):
        for setting in ("PLEX_URL", "PLEX_API"):
            with self.subTest(setting), patch.dict(os.environ):
                del os.environ[setting]
                self.faults.reports.clear()

                self.assertIsNone(await self.plex().link(DUNE, "film"))

                [report] = self.faults.reports
                fault = report.fault
                self.assertEqual((fault.kind, fault.service, fault.check, fault.item, fault.what),
                                 (FaultKind.SETUP, "plex", "setting", setting, f"{setting} is not set"))
                self.assertEqual(report.continued, "sent the answer without a Plex link")
                self.plex_server.assert_not_called()

    async def test_a_token_that_plex_does_not_accept_is_an_inrichtingsfout_of_plex_api(self):
        self.plex_server.side_effect = Unauthorized(f"(401) unauthorized; {URL}/ <html>Unauthorized</html>")

        await self.plex().link(DUNE, "film")

        [report] = self.faults.reports
        fault = report.fault
        self.assertEqual((fault.kind, fault.service, fault.check, fault.item, fault.http_status, fault.what),
                         (FaultKind.SETUP, "plex", "setting", "PLEX_API", 401, "Plex does not accept PLEX_API"))

    async def test_a_url_that_does_not_lead_to_plex_is_an_inrichtingsfout_of_plex_url(self):
        for error in (requests.exceptions.MissingSchema("Invalid URL 'plex:32400/': No scheme supplied."),
                      NotFound(f"(404) not_found; {URL}/ <html>Not Found</html>"),
                      ParseError("mismatched tag: line 12, column 2")):
            with self.subTest(type(error).__name__):
                self.plex_server.side_effect = error
                self.faults.reports.clear()

                await self.plex().link(DUNE, "film")

                [report] = self.faults.reports
                fault = report.fault
                self.assertEqual((fault.kind, fault.service, fault.check, fault.item, fault.what),
                                 (FaultKind.SETUP, "plex", "setting", "PLEX_URL", "PLEX_URL does not lead to Plex"))

    async def test_no_match_in_plex_is_a_warning_and_no_fault(self):
        self.server.library.section.return_value.search.return_value = []

        self.assertIsNone(await self.plex().link(DUNE, "film"))

        self.assertEqual(self.faults.reports, [])
        [line] = self.read(MAIN)
        self.assertEqual((line["level"], line["msg"]), ("WARNING", "no match in Plex for 'Dune' in Movies"))
        self.assertEqual((line["media_title"], line["media_year"], line["tmdb_id"]), ("Dune", 2021, 438631))
        self.assertNotIn("fault", line)

    async def test_media_without_a_title_is_an_inrichtingsfout_of_radarr_or_sonarr(self):
        self.assertIsNone(await self.plex().link({"title": " ", "tmdbId": 1399}, "serie"))

        [report] = self.faults.reports
        fault = report.fault
        self.assertEqual((fault.kind, fault.service, fault.check, fault.item, fault.what),
                         (FaultKind.SETUP, "sonarr", "media_title", 1399, "Sonarr gives no title for tmdb 1399"))
        self.assertEqual(report.continued, "sent the answer without a Plex link")
        self.plex_server.assert_not_called()

    async def test_an_unexpected_exception_is_one_bug_and_the_answer_goes_on_without_a_link(self):
        no_library = NotFound("Invalid library section: Movies")
        self.server.library.section.side_effect = no_library

        self.assertIsNone(await self.plex().link(DUNE, "film"))

        [report] = self.faults.reports
        fault = report.fault
        self.assertEqual((fault.kind, fault.service, fault.what), (FaultKind.BUG, "plex", "Making a Plex link failed"))
        self.assertIs(fault.__cause__, no_library)
        self.assertEqual(report.continued, "sent the answer without a Plex link")

    async def test_an_unexpected_exception_at_the_connection_is_a_bug_too(self):
        self.plex_server.side_effect = TypeError("'NoneType' object is not subscriptable")

        await self.plex().link(DUNE, "film")

        [report] = self.faults.reports
        self.assertEqual((report.fault.kind, report.fault.service), (FaultKind.BUG, "plex"))
        self.assertIsInstance(report.fault.__cause__, TypeError)

    async def test_an_exception_while_making_the_link_is_a_bug_and_the_answer_goes_on(self):
        self.server.library.section.return_value.search.return_value = [SimpleNamespace(title="Dune")]

        self.assertIsNone(await self.plex().link(DUNE, "film"))

        [report] = self.faults.reports
        self.assertEqual((report.fault.kind, report.fault.what), (FaultKind.BUG, "Making a Plex link failed"))
        self.assertIsInstance(report.fault.__cause__, AttributeError)

    async def test_the_first_of_a_list_of_lookup_results(self):
        self.assertEqual(await self.plex().link([DUNE, {"title": "Dune: Part Two"}], "film"), LINK)

        self.server.library.section.return_value.search.assert_called_once_with("Dune")


if __name__ == "__main__":
    unittest.main()
