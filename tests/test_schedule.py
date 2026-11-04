#!/usr/bin/python3

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.commands.schedule import Schedule
from src.faults import Fault, FaultKind
from src.log import setup_logging
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
        self.enterContext(patch("src.commands.schedule.check_transmission_and_trigger_scans", AsyncMock()))

        self.telegram = MagicMock()
        self.telegram.send_user_message = AsyncMock(return_value=DELIVERED)
        self.telegram.send_admin_message = AsyncMock()
        functions = MagicMock(sanitize_text=lambda text: text)
        self.faults = FakeFaults()
        self.schedule = Schedule(SimpleNamespace(env="dev"), MagicMock(), functions, self.telegram, self.faults)
        self.schedule.plex.get_media_url = AsyncMock(return_value=None)

        # The movies and series as Radarr and Sonarr have them, each with a folder that has its file
        self.media = {}
        for tmdb_id, title in (("1001", "Dune"), ("1002", "Arrival"), ("1399", "Game of Thrones")):
            folder = self.folder / "media" / title
            (folder / "S01").mkdir(parents=True)
            (folder / "S01" / f"{title} S01E01.mkv").write_text("")
            self.media[tmdb_id] = {"title": title, "year": 2016, "tmdbId": int(tmdb_id), "path": str(folder),
                                   "statistics": {"seasonCount": 1}, "ended": True}
        self.schedule.radarr = MagicMock(service="radarr", lookup_by_tmdbid=AsyncMock(side_effect=self.lookup))
        self.schedule.sonarr = MagicMock(service="sonarr", lookup_by_tmdbid=AsyncMock(side_effect=self.lookup))

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

    async def test_everyone_is_told(self):
        await self.schedule.check_notify_list(None)

        self.assertEqual(self.notified(), ["Dune", "Game of Thrones", "Arrival"])
        self.assertEqual(self.waiting(), {"1": [], "2": []})
        self.assertEqual(self.faults.reports, [])

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


if __name__ == "__main__":
    unittest.main()
