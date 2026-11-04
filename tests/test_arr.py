#!/usr/bin/python3

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestServer

from src.faults import Fault, FaultKind
from src.log import setup_logging
from src.services.arr import media_link
from src.services.radarr import Radarr
from src.services.sonarr import Sonarr
from test_interaction import FakeFaults
from test_log import DEBUG, SECRETS, LogFolder


# What Radarr answers to a movie that is already in Radarr
ALREADY_ADDED = [{"propertyName": "TmdbId", "errorMessage": "This movie has already been added",
                  "attemptedValue": 803796, "severity": "error", "errorCode": "MovieExistsValidator"}]

GAME_OF_THRONES = {"title": "Game of Thrones", "year": 2011, "tmdbId": 1399, "titleSlug": "game-of-thrones",
                   "path": "/media/series/Game of Thrones"}


class ArrTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ Radarr and Sonarr clients against a fake Radarr and Sonarr on localhost, with a fake meldfunctie """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "DEBUG", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))
        self.enterContext(patch("src.services.request.asyncio.sleep", AsyncMock()))
        self.faults = FakeFaults()

        # Per method and path the answers still to give, and every request the fake server got
        self.answers = {}
        self.requests = []

    async def asyncSetUp(self):
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", self.handle)
        self.server = TestServer(app)
        await self.server.start_server()
        self.addAsyncCleanup(self.server.close)
        self.enterContext(patch.dict(os.environ, {"RADARR_URL": self.url(), "SONARR_URL": self.url()}))

    def url(self, path: str = "") -> str:
        """ The URL of the API on the fake server, as RADARR_URL has it """
        return str(self.server.make_url(f"/api/v3{path}"))

    async def handle(self, request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else None
        self.requests.append((request.method, request.path, dict(request.query), body))
        status, answer = self.answers[(request.method, request.path)].pop(0)
        if isinstance(answer, str):
            return web.Response(status=status, text=answer)
        return web.json_response(answer, status=status)

    def answer(self, method: str, path: str, *answers: tuple[int, object]) -> None:
        """ What the fake server answers to the next requests to this path of the API, one per request """
        self.answers[(method, f"/api/v3{path}")] = list(answers)

    def http_calls(self) -> list[dict]:
        return [line for line in self.read(DEBUG) if line.get("event") == "http_call"]

    async def test_the_key_goes_as_a_parameter_and_not_into_the_http_call(self):
        self.answer("GET", "/movie/lookup", (200, [{"title": "Dune", "year": 2021}]))

        self.assertEqual(await Radarr(self.faults).lookup_by_name("dune"), [{"title": "Dune", "year": 2021}])

        [(_, _, query, _)] = self.requests
        self.assertEqual(query, {"term": "dune", "apikey": SECRETS["RADARR_API"]})
        [line] = self.http_calls()
        self.assertEqual((line["service"], line["method"], line["url"], line["http_status"]),
                         ("radarr", "GET", self.url("/movie/lookup?term=dune"), 200))
        self.assertNotIn("apikey", json.dumps(line))
        self.assertEqual(self.faults.oks, ["radarr"])

    async def test_radarr_refusing_a_movie_is_a_bug_with_its_reason(self):
        self.answer("POST", "/movie", (400, ALREADY_ADDED))

        with self.assertRaises(Fault) as caught:
            await Radarr(self.faults).queue_download({"tmdbId": 803796, "monitored": True})

        fault = caught.exception
        self.assertEqual((fault.kind, fault.service, fault.what, fault.reason, fault.http_status),
                         (FaultKind.BUG, "radarr", "Radarr refused the movie request",
                          "This movie has already been added", 400))
        [(_, _, _, sent)] = self.requests
        self.assertEqual(sent, {"tmdbId": 803796, "monitored": True})

    async def test_a_503_is_tried_three_times(self):
        self.answer("POST", "/series", *[(503, "Service Unavailable")] * 3)

        with self.assertRaises(Fault) as caught:
            await Sonarr(self.faults).queue_download({"tvdbId": 121361})

        fault = caught.exception
        self.assertEqual((fault.kind, fault.what, fault.reason, fault.http_status),
                         (FaultKind.DISRUPTION, "Sonarr is not responding", "Service Unavailable", 503))
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(len(self.http_calls()), 3)

    async def test_a_page_of_a_proxy_is_no_reason(self):
        self.answer("GET", "/diskspace", *[(502, "<html><body><h1>502 Bad Gateway</h1></body></html>")] * 3)

        with self.assertRaises(Fault) as caught:
            await Radarr(self.faults).get_disk_space()

        self.assertEqual(caught.exception.reason, "Bad Gateway")

    async def test_radarr_that_cannot_be_reached_is_a_storing(self):
        # A port where nothing listens anymore
        url = self.url()
        await self.server.close()

        with patch.dict(os.environ, {"RADARR_URL": url}):
            with self.assertRaises(Fault) as caught:
                await Radarr(self.faults).scan_missing_media()

        fault = caught.exception
        self.assertEqual((fault.kind, fault.what), (FaultKind.DISRUPTION, "Radarr is not responding"))
        self.assertIsNotNone(fault.__cause__)

    async def test_the_search_for_missing_media(self):
        for client, name in ((Radarr, "missingMoviesSearch"), (Sonarr, "MissingEpisodeSearch")):
            with self.subTest(client=client.__name__):
                self.requests.clear()
                self.answer("POST", "/command", (201, {"id": 7, "name": name}))

                self.assertEqual(await client(self.faults).scan_missing_media(), {"id": 7, "name": name})
                [(_, _, _, sent)] = self.requests
                self.assertEqual(sent, {"name": name, "filterKey": "monitored", "filterValue": "true"})

    async def test_lookup_by_tmdbid_gives_the_item_and_passes_the_check(self):
        self.answer("GET", "/series/lookup", (200, [GAME_OF_THRONES]))

        self.assertEqual(await Sonarr(self.faults).lookup_by_tmdbid("1399"), GAME_OF_THRONES)

        [(_, _, query, _)] = self.requests
        self.assertEqual(query["term"], "tmdb:1399")
        [fix] = [fix for fix in self.faults.fixes if fix.check == "tmdb_lookup"]
        self.assertEqual((fix.service, fix.item, fix.msg),
                         ("sonarr", "1399", "Sonarr finds Game of Thrones for tmdb 1399 again"))

    async def test_a_lookup_that_finds_nothing_is_an_inrichtingsfout(self):
        self.answer("GET", "/movie/lookup", (200, []))

        with self.assertRaises(Fault) as caught:
            await Radarr(self.faults).lookup_by_tmdbid("1593993")

        fault = caught.exception
        self.assertEqual((fault.kind, fault.service, fault.check, fault.item, fault.what),
                         (FaultKind.SETUP, "radarr", "tmdb_lookup", "1593993", "Radarr finds nothing for tmdb 1593993"))
        self.assertEqual([fix for fix in self.faults.fixes if fix.check == "tmdb_lookup"], [])

    async def test_a_lookup_that_finds_another_series_is_the_same_inrichtingsfout(self):
        # SkyHook sometimes answers a tmdb: search with a completely different series
        self.answer("GET", "/series/lookup", (200, [{**GAME_OF_THRONES, "title": "Ghosts", "tmdbId": 2}]))

        with self.assertRaises(Fault) as caught:
            await Sonarr(self.faults).lookup_by_tmdbid("1399")

        fault = caught.exception
        self.assertEqual((fault.kind, fault.check, fault.item, fault.what),
                         (FaultKind.SETUP, "tmdb_lookup", "1399", "Sonarr finds another series for tmdb 1399"))
        self.assertEqual(fault.details, {"title": "Ghosts", "tmdbId": 2})


class MediaLinkTest(unittest.TestCase):
    """ The link on the line Media: of an admin message, to the item in the web interface of Radarr or Sonarr """

    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"RADARR_URL": "https://radarr.example.com/api/v3",
                                                  "SONARR_URL": "https://sonarr.example.com/api/v3/"}))

    def test_radarr_names_a_movie_by_its_tmdbid(self):
        self.assertEqual(media_link("radarr", {"title": "Dune: Part Two", "tmdbId": 693134}),
                         "https://radarr.example.com/movie/693134")
        self.assertEqual(media_link("radarr", {"titleSlug": "1314481", "tmdbId": 1314481}),
                         "https://radarr.example.com/movie/1314481")

    def test_sonarr_names_a_series_by_its_slug(self):
        self.assertEqual(media_link("sonarr", GAME_OF_THRONES), "https://sonarr.example.com/series/game-of-thrones")

    def test_no_link_without_the_slug_or_for_another_service(self):
        self.assertIsNone(media_link("sonarr", {"title": "Carrie", "tmdbId": 288673}))
        self.assertIsNone(media_link("plex", {"title": "Dune", "tmdbId": 438631}))

    def test_a_url_without_the_path_of_the_api(self):
        with patch.dict(os.environ, {"RADARR_URL": "https://radarr.example.com/"}):
            self.assertEqual(media_link("radarr", {"tmdbId": 1}), "https://radarr.example.com/movie/1")


if __name__ == "__main__":
    unittest.main()
