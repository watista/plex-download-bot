#!/usr/bin/python3

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import requests

from src.commands.schedule import Schedule
from src.faults import Fault, FaultKind
from src.log import setup_logging
from src.services.plex import Plex
from src.telegram_out import DELIVERED
from test_interaction import FakeFaults
from test_log import LogFolder


class CheckNotifyListTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ check_notify_list with a fake Radarr, Sonarr, Plex and Telegram, on a data.json and media folders in a
    temporary folder. Anna waits for a movie, Bob for a movie and a series. """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:30:00+01:00"))
        self.enterContext(patch.dict(os.environ, {"PLEX_URL": "http://plex.example.com:32400", "PLEX_ID": "server-id"}))

        self.telegram = MagicMock()
        self.telegram.send_user_message = AsyncMock(return_value=DELIVERED)
        self.telegram.send_admin_message = AsyncMock()
        functions = MagicMock(sanitize_text=lambda text: text)
        self.faults = FakeFaults()
        self.schedule = Schedule(SimpleNamespace(env="dev"), MagicMock(), functions, self.telegram, self.faults)
        self.schedule.transmission = MagicMock()
        self.schedule.plex.link = AsyncMock(return_value=None)

        # The movies and series as Radarr and Sonarr have them, each with a folder that has its file
        self.media = {}
        for tmdb_id, title in (("1001", "Dune"), ("1002", "Arrival"), ("1399", "Game of Thrones")):
            folder = self.folder / "media" / title
            (folder / "S01").mkdir(parents=True)
            (folder / "S01" / f"{title} S01E01.mkv").write_text("")
            self.media[tmdb_id] = {"title": title, "year": 2016, "tmdbId": int(tmdb_id), "path": str(folder),
                                   "statistics": {"seasonCount": 1}, "ended": True}
        for name, service, media_type in (("radarr", "radarr", "movie"), ("sonarr", "sonarr", "series")):
            setattr(self.schedule, name, MagicMock(service=service, media_type=media_type,
                                                   lookup_by_tmdbid=AsyncMock(side_effect=self.lookup)))

        self.data_json = self.folder / "data.dev.json"
        self.data_json.write_text(json.dumps({
            "user_id": {"1": "anna, Anna", "2": "bob, Bob"},
            "notify_list": {"1": {"film": {"1001": 1}}, "2": {"film": {"1002": 1}, "serie": {"1399": 1}}},
        }))
        self.schedule.data_json = str(self.data_json)

    async def lookup(self, tmdb_id: str) -> dict:
        """ The lookup of Radarr or Sonarr: the item, or the Fault the test put there """
        answer = self.media[tmdb_id]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def waiting(self) -> dict:
        """ Per user, the movies and series in data.json that the user still waits for """
        notify_list = json.loads(self.data_json.read_text())["notify_list"]
        return {user: sorted(tmdb_id for kind in ("film", "serie") for tmdb_id in media.get(kind, {}))
                for user, media in notify_list.items()}

    def notified(self) -> list[str]:
        """ The titles in the Gebruikersberichten that went out """
        return [c.args[3]["title"] for c in self.telegram.send_user_message.await_args_list]

    def messages(self) -> list[str]:
        """ The texts of the Gebruikersberichten that went out """
        return [c.args[2] for c in self.telegram.send_user_message.await_args_list]

    def plex(self, failing: Exception | None = None) -> None:
        """ Gives the schedule a real client of Plex, on a fake PlexServer that has every movie and series under its
        tmdb ID, or that cannot be made with this exception """
        server = MagicMock()
        server.library.section.return_value.search.side_effect = lambda title: [SimpleNamespace(
            title=title, ratingKey=next(key for key, item in self.media.items() if item["title"] == title))]
        self.enterContext(patch("src.services.plex.PlexServer", return_value=server, side_effect=failing))
        self.schedule.plex = Plex(self.faults)

    async def test_everyone_is_told(self):
        await self.schedule.check_notify_list(None)

        self.assertEqual(self.notified(), ["Dune", "Game of Thrones", "Arrival"])
        self.assertEqual(self.waiting(), {"1": [], "2": []})
        self.assertEqual(self.faults.reports, [])

    async def test_transmission_is_no_part_of_it(self):
        await self.schedule.check_notify_list(None)

        self.assertEqual(self.schedule.transmission.mock_calls, [])

    async def test_a_message_has_the_link_to_the_media_in_plex(self):
        self.plex()

        await self.schedule.check_notify_list(None)

        self.assertIn('🌐 <a href="https://app.plex.tv/desktop/#!/server/server-id/details?'
                      'key=%2Flibrary%2Fmetadata%2F1001">Bekijk Dune in de browser</a>', self.messages()[0])

    async def test_a_plex_link_that_fails_is_reported_once_and_the_message_goes_without_it(self):
        self.plex(failing=requests.exceptions.ConnectionError("Connection refused"))

        await self.schedule.check_notify_list(None)

        # One Fout of Plex for the run: after a connection that failed, the next links wait
        [report] = self.faults.reports
        self.assertEqual((report.fault.kind, report.fault.service), (FaultKind.DISRUPTION, "plex"))
        self.assertEqual(report.continued, "sent the answer without a Plex link")
        self.assertEqual(self.notified(), ["Dune", "Game of Thrones", "Arrival"])
        self.assertTrue(all("🌐" not in message for message in self.messages()))

    async def test_a_movie_that_radarr_does_not_find_is_reported_and_skipped(self):
        not_found = Fault.setup(service="radarr", what="Radarr finds nothing for tmdb 1001", check="tmdb_lookup",
                                item="1001")
        self.media["1001"] = not_found

        await self.schedule.check_notify_list(None)

        [report] = self.faults.reports
        self.assertEqual((report.fault, report.continued), (not_found, "skipped this item"))
        self.assertEqual(self.notified(), ["Game of Thrones", "Arrival"])
        self.assertEqual(self.waiting(), {"1": ["1001"], "2": []})

    async def test_a_series_without_a_path_is_an_inrichtingsfout_and_skipped(self):
        del self.media["1399"]["path"]

        await self.schedule.check_notify_list(None)

        [report] = self.faults.reports
        fault = report.fault
        self.assertEqual((fault.kind, fault.service, fault.check, fault.item, fault.what),
                         (FaultKind.SETUP, "sonarr", "series_path", "1399", "Game of Thrones has no path in Sonarr"))
        self.assertEqual(fault.media["title"], "Game of Thrones")
        self.assertEqual(report.continued, "skipped this item")
        self.assertEqual(self.notified(), ["Dune", "Arrival"])
        self.assertEqual(self.waiting(), {"1": [], "2": ["1399"]})

    async def test_a_movie_without_a_path_is_an_inrichtingsfout_too(self):
        del self.media["1002"]["path"]

        await self.schedule.check_notify_list(None)

        [report] = self.faults.reports
        self.assertEqual((report.fault.check, report.fault.what), ("movie_path", "Arrival has no path in Radarr"))

    async def test_a_media_item_with_a_path_passes_the_check(self):
        await self.schedule.check_notify_list(None)

        self.assertEqual([(fix.service, fix.check, fix.item, fix.msg) for fix in self.faults.fixes], [
            ("radarr", "movie_path", "1001", "Dune now has a path in Radarr"),
            ("sonarr", "series_path", "1399", "Game of Thrones now has a path in Sonarr"),
            ("radarr", "movie_path", "1002", "Arrival now has a path in Radarr"),
        ])

    async def test_a_key_that_radarr_does_not_accept_ends_the_run(self):
        # An Inrichtingsfout too, but not of one item: every next item would run into it
        wrong_key = Fault.setup(service="radarr", what="Radarr does not accept RADARR_API", check="setting",
                                item="RADARR_API", http_status=401)
        self.media["1001"] = wrong_key

        with self.assertRaises(Fault) as caught:
            await self.schedule.check_notify_list(None)

        self.assertIs(caught.exception, wrong_key)
        self.assertEqual(self.faults.reports, [])
        self.assertEqual(self.notified(), [])

    async def test_a_storing_ends_the_run_and_keeps_what_it_did(self):
        not_responding = Fault.disruption(service="radarr", what="Radarr is not responding", http_status=503)
        self.media["1002"] = not_responding

        with self.assertRaises(Fault) as caught:
            await self.schedule.check_notify_list(None)

        # The wrapper of the job reports it; who was told before it does not get the same message next run
        self.assertIs(caught.exception, not_responding)
        self.assertEqual(self.faults.reports, [])
        self.assertEqual(self.notified(), ["Dune", "Game of Thrones"])
        self.assertEqual(self.waiting(), {"1": [], "2": ["1002"]})


# What the client of Transmission raises while Transmission does not answer
NOT_RESPONDING = Fault.disruption(service="transmission", what="Transmission is not responding")


class CheckTransmissionTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ check_transmission with a fake Transmission, Sonarr and Radarr. Every run is a new call on the same Schedule;
    a restart is a new Schedule. """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T15:00:00+01:00"))
        self.faults = FakeFaults()

        # The searches that started, in order, each with the number of lines transmission_back written before it
        self.searches = []
        self.schedule = self.restart()

    def restart(self) -> Schedule:
        """ A Schedule as the bot makes it when it starts, with a Transmission that answers """
        schedule = Schedule(SimpleNamespace(env="dev"), MagicMock(), MagicMock(), MagicMock(), self.faults)
        schedule.transmission = MagicMock(check=AsyncMock())
        for name in ("sonarr", "radarr"):
            setattr(schedule, name, MagicMock(scan_missing_media=AsyncMock(side_effect=self.search(name))))
        return schedule

    def search(self, name: str):
        """ The search for the missing media of this service, which notes that it started """
        async def scan_missing_media() -> dict:
            self.searches.append((name, len(self.lines("transmission_back"))))
            return {}
        return scan_missing_media

    def down(self) -> None:
        self.schedule.transmission.check.side_effect = NOT_RESPONDING

    def up(self) -> None:
        self.schedule.transmission.check.side_effect = None

    async def run_down(self) -> None:
        """ A run while Transmission does not answer: the Storing ends it, and goes to the wrapper of the job """
        self.down()
        with self.assertRaises(Fault) as caught:
            await self.schedule.check_transmission(None)
        self.assertIs(caught.exception, NOT_RESPONDING)

    async def test_transmission_back_after_a_run_it_was_down_starts_both_searches(self):
        await self.schedule.check_transmission(None)
        await self.run_down()
        self.up()

        await self.schedule.check_transmission(None)

        # The line first, then both searches
        self.assertEqual(self.searches, [("sonarr", 1), ("radarr", 1)])
        [line] = self.lines("transmission_back")
        self.assertEqual((line["level"], line["msg"], line["logger"]),
                         ("INFO", "Transmission is back: starting the missing searches in Sonarr and Radarr",
                          "commands.schedule"))
        self.assertEqual(self.faults.reports, [])

    async def test_down_at_the_first_run_after_a_restart_and_then_back(self):
        await self.run_down()
        self.up()

        await self.schedule.check_transmission(None)

        self.assertEqual(self.searches, [("sonarr", 1), ("radarr", 1)])

    async def test_the_first_run_after_a_restart_starts_nothing(self):
        await self.schedule.check_transmission(None)
        await self.run_down()

        # After the restart the bot does not know that Transmission was down
        self.schedule = self.restart()
        await self.schedule.check_transmission(None)

        self.assertEqual(self.searches, [])
        self.assertEqual(self.lines("transmission_back"), [])

    async def test_a_transmission_that_stays_up_starts_nothing(self):
        await self.schedule.check_transmission(None)
        await self.schedule.check_transmission(None)

        self.assertEqual(self.searches, [])

    async def test_a_transmission_that_stays_down_starts_nothing(self):
        await self.run_down()
        await self.run_down()

        self.assertEqual(self.searches, [])

    async def test_a_search_that_fails_ends_the_run_after_the_line(self):
        await self.run_down()
        self.up()
        failed = Fault.disruption(service="sonarr", what="Sonarr is not responding", http_status=503)
        self.schedule.sonarr.scan_missing_media.side_effect = failed

        with self.assertRaises(Fault) as caught:
            await self.schedule.check_transmission(None)

        self.assertIs(caught.exception, failed)
        self.assertEqual(len(self.lines("transmission_back")), 1)
        self.schedule.radarr.scan_missing_media.assert_not_awaited()

        # Transmission was up at that run, so the next run does not search again
        self.schedule.sonarr.scan_missing_media.side_effect = None
        await self.schedule.check_transmission(None)
        self.assertEqual(self.schedule.sonarr.scan_missing_media.await_count, 1)


if __name__ == "__main__":
    unittest.main()
