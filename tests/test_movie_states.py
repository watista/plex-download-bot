#!/usr/bin/python3

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.commands.movie import Movie
from src.states import MOVIE_NOTIFY, MOVIE_OPTION


# Radarr lookup result for a movie that is not in Radarr yet: no id, never monitored
NEW_MOVIE = {
    "title": "New Movie",
    "year": 2025,
    "tmdbId": 1001,
    "status": "released",
    "monitored": False,
    "hasFile": False,
    "movieFileId": 0,
}

# Radarr lookup result for a movie that is already in Radarr, but unmonitored and without a file.
# This is how KPop Demon Hunters (tmdbId 803796) came back in October 2026: the POST to /movie
# answered 400 "This movie has already been added".
IN_RADARR_UNMONITORED = {
    "id": 412,
    "title": "KPop Demon Hunters",
    "year": 2025,
    "tmdbId": 803796,
    "status": "released",
    "monitored": False,
    "hasFile": False,
    "movieFileId": 0,
    "path": "/media/beide2/movies/KPop Demon Hunters (2025)",
}


class MovieStateTest(unittest.IsolatedAsyncioTestCase):
    """ Checks which route media_option takes for a chosen movie """

    def setUp(self):

        # Logger and functions without Telegram
        self.log = MagicMock()
        self.log.logger = AsyncMock()
        functions = MagicMock()
        functions.sanitize_text = lambda text: text
        functions.send_message = AsyncMock()

        # Movie with a fake Radarr that has room on its disk
        self.movie = Movie(SimpleNamespace(env="dev"), self.log, functions)
        self.radarr = MagicMock()
        self.radarr.get_disk_space = AsyncMock(return_value=[{"path": "/media", "freeSpace": 500 * 1024 ** 3}])
        self.radarr.queue_download = AsyncMock(return_value={"id": 1})
        self.radarr.scan_missing_media = AsyncMock()
        self.movie.media_handler = self.radarr
        self.movie.write_to_stats = AsyncMock()

        # Transmission is up and has no active torrents
        transmission = MagicMock()
        transmission.return_value.get_active_torrents = AsyncMock(return_value=(True, []))
        for target, value in [
            ("src.commands.media.TransmissionService", transmission),
            ("src.commands.media.check_transmission_and_trigger_scans", AsyncMock()),
            ("src.commands.media.asyncio.sleep", AsyncMock()),
        ]:
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def choose(self, lookup: dict, **user_data) -> int:
        """ Lets the user choose the given lookup result as option 1 """

        update = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.data = "0"
        update.effective_user.id = 1
        update.effective_user.first_name = "Test"

        context = MagicMock()
        context.user_data = {
            "label": "film",
            "media_folder": "/media/movies",
            "option_state": MOVIE_OPTION,
            "gebruiker": "test",
            "media_object": [dict(lookup)],
            **user_data,
        }

        return await self.movie.media_option(update, context)

    def admin_messages(self) -> list[str]:
        """ Messages that went to the Beheerder on Telegram (telegram is the 4th argument, default True) """
        return [c.args[0] for c in self.log.logger.await_args_list if len(c.args) < 4 or c.args[3]]

    async def test_new_movie_is_added_to_radarr(self):
        state = await self.choose(NEW_MOVIE)

        self.assertEqual(state, MOVIE_NOTIFY)
        self.radarr.queue_download.assert_awaited_once()
        self.assertEqual(self.radarr.queue_download.await_args.args[0]["tmdbId"], 1001)

    async def test_unmonitored_movie_in_radarr_is_not_added_again(self):
        state = await self.choose(IN_RADARR_UNMONITORED)

        self.assertEqual(state, MOVIE_NOTIFY)
        self.radarr.queue_download.assert_not_awaited()
        self.assertTrue(any("marked as unmonitored" in msg for msg in self.admin_messages()))

    async def test_unreleased_unmonitored_movie_in_radarr_is_not_added_again(self):
        state = await self.choose({**IN_RADARR_UNMONITORED, "status": "announced"})

        self.assertEqual(state, MOVIE_NOTIFY)
        self.radarr.queue_download.assert_not_awaited()
        self.assertTrue(any("marked as unmonitored" in msg for msg in self.admin_messages()))

    async def test_unmonitor_flag_of_an_earlier_big_serie_is_not_used(self):
        # A serie with more than 5 seasons sets set_monitored to False. The persisted user_data kept
        # it, so every later movie of that Gebruiker was added unmonitored and never searched.
        await self.choose(NEW_MOVIE, set_monitored=False)

        self.radarr.queue_download.assert_awaited_once()
        self.assertTrue(self.radarr.queue_download.await_args.args[0]["monitored"])


if __name__ == "__main__":
    unittest.main()
