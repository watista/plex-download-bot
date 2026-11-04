#!/usr/bin/python3

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.ext import ConversationHandler

from src.commands.serie import Serie
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
        self.serie = Serie(SimpleNamespace(env="dev"), self.log, self.functions, self.telegram)
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
