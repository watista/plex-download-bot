#!/usr/bin/python3

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.ext import ConversationHandler

from src.commands.serie import Serie
from src.faults import Fault, FaultKind
from src.states import SERIE_NOTIFY, SERIE_OPTION
from test_log import MAIN
from test_movie_states import MovieTest


# Sonarr lookup result for a serie that is not in Sonarr yet, with more than 5 seasons
THE_SIMPSONS = {
    "title": "The Simpsons",
    "year": 1989,
    "tmdbId": 456,
    "tvdbId": 71663,
    "status": "continuing",
    "monitored": False,
    "statistics": {"seasonCount": 36},
}

# Sonarr lookup result for a serie that is downløaded and still running
THE_BEAR = {"title": "The Bear", "year": 2022, "tmdbId": 136315, "tvdbId": 1, "path": "/media/series/The Bear"}


class SerieTest(MovieTest):
    """ A Serie with a fake Sonarr, Transmission and Telegram, and its log lines in a temporary folder """

    def setUp(self):
        super().setUp()
        self.serie = Serie(SimpleNamespace(env="dev"), self.functions, self.telegram, self.faults)
        self.serie.media_handler = self.radarr
        self.serie.write_to_stats = AsyncMock()

        # A data.json without subscriptions
        self.data_json = self.folder / "data.dev.json"
        self.data_json.write_text(json.dumps({"notify_list": {}}))
        self.serie.data_json = str(self.data_json)

    def context(self, **user_data):
        return super().context(**{"label": "serie", "media_folder": "/media/series", "option_state": SERIE_OPTION,
                                   "media_type": "serie", **user_data})

    async def test_serie_with_more_than_5_seasons_is_added_unmonitored(self):
        state = await self.serie.media_option(self.update("0"), self.context(media_object=[dict(THE_SIMPSONS)]))

        self.assertEqual(state, SERIE_NOTIFY)
        self.assertFalse(self.radarr.queue_download.await_args.args[0]["monitored"])
        [line] = self.lines("media_request")
        self.assertEqual(line["msg"], "chose option 1: The Simpsons (1989): unmonitored, 36 seasons")
        self.assertEqual((line["outcome"], line["seasons"], line["media_type"], line["tmdb_id"]),
                         ("unmonitored", 36, "series", 456))
        self.assertNotIn("tvdb", self.raw(MAIN))
        [message] = self.admin_messages()
        self.assertIn("with 36 seasons", message)

    async def test_subscribe_after_a_request(self):
        state = await self.serie.aanmelden(self.update("yes"), self.context(media_data=dict(THE_BEAR)))

        self.assertEqual(state, ConversationHandler.END)
        [line] = self.lines("series_updates")
        self.assertEqual(line["msg"], "new episodes of The Bear (2022): yes: subscribed")
        self.assertEqual((line["choice"], line["outcome"], line["tmdb_id"]), ("yes", "subscribed", 136315))
        [message] = self.admin_messages()
        self.assertIn("User has subscribed to the serie The Bear", message)

        # The series has its path in Sonarr
        [fix] = self.faults.fixes
        self.assertEqual((fix.service, fix.check, fix.item, fix.msg),
                         ("sonarr", "series_path", 136315, "The Bear now has a path in Sonarr"))
        self.assertEqual(self.faults.reports, [])

    async def test_a_new_series_gets_its_path_from_the_answer_of_sonarr(self):
        # The lookup is from before the series was in Sonarr, so it has no path; the answer to the request has one
        self.radarr.queue_download = AsyncMock(return_value={"id": 9, "path": "/media/series/The Simpsons"})
        context = self.context(media_object=[dict(THE_SIMPSONS)])

        await self.serie.media_option(self.update("0"), context)
        await self.serie.aanmelden(self.update("yes"), context)

        self.assertEqual(context.user_data["media_data"]["path"], "/media/series/The Simpsons")
        self.assertEqual(self.faults.reports, [])
        self.assertEqual([fix.check for fix in self.faults.fixes], ["setting", "disk_space", "series_path"])

    async def test_subscribing_to_a_series_without_a_path_is_reported_and_goes_on(self):
        without_path = {key: value for key, value in THE_BEAR.items() if key != "path"}

        state = await self.serie.aanmelden(self.update("yes"), self.context(media_data=without_path))

        self.assertEqual(state, ConversationHandler.END)
        [report] = self.faults.reports
        fault = report.fault
        self.assertEqual((fault.kind, fault.service, fault.check, fault.item, fault.what),
                         (FaultKind.SETUP, "sonarr", "series_path", 136315, "The Bear has no path in Sonarr"))
        self.assertEqual(fault.media["title"], "The Bear")
        self.assertEqual(report.continued, "subscribed from the first episode on")
        self.assertEqual(json.loads(self.data_json.read_text())["notify_list"]["1"]["serie_episode"],
                         {"136315": {"started": False, "last": "S00E00"}})
        [line] = self.lines("series_updates")
        self.assertEqual(line["outcome"], "subscribed")
        self.assertEqual(self.faults.fixes, [])

    async def test_subscribing_to_a_serie_without_a_tmdbId_is_a_bug(self):
        without_id = {key: value for key, value in THE_BEAR.items() if key != "tmdbId"}
        context = self.context(media_data=without_id, media_item={"title": "The Bear", "year": 2022, "tmdbId": None})

        with self.assertRaises(Fault) as caught:
            await self.serie.aanmelden(self.update("yes"), context)

        fault = caught.exception
        self.assertEqual((fault.kind, fault.what, fault.details), (FaultKind.BUG, "The series has no tmdbId",
                                                                   {"tmdbId": None}))
        self.assertEqual(fault.media["title"], "The Bear")
        self.functions.send_message.assert_not_awaited()
        self.assertEqual(json.loads(self.data_json.read_text()), {"notify_list": {}})

    async def test_a_serie_without_a_tvdbId_falls_through_to_the_wrapper(self):
        without_id = {key: value for key, value in THE_SIMPSONS.items() if key != "tvdbId"}

        with self.assertRaises(KeyError):
            await self.serie.media_option(self.update("0"), self.context(media_object=[without_id]))

    async def test_no_subscription_after_a_request(self):
        await self.serie.aanmelden(self.update("no"), self.context(media_data=dict(THE_BEAR)))

        [line] = self.lines("series_updates")
        self.assertEqual((line["msg"], line["choice"]), ("new episodes of The Bear (2022): no", "no"))
        self.assertNotIn("outcome", line)

    async def test_quality_request_for_an_episode(self):
        context = self.context(media_data=dict(THE_BEAR))

        await self.serie.media_upgrade_info(self.update("missing"), context)
        await self.serie.media_upgrade_option(self.update(text="S02E03"), context)

        self.assertEqual([(line["msg"], line["reason"], line.get("text")) for line in self.lines("quality_request")], [
            ("quality request for The Bear (2022): missing", "missing", None),
            ("quality request for The Bear (2022): missing: 'S02E03'", "missing", "S02E03"),
        ])


if __name__ == "__main__":
    unittest.main()
