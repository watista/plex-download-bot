#!/usr/bin/python3

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import requests
from telegram.ext import ConversationHandler

from src.commands.movie import Movie
from src.faults import Fault, FaultKind
from src.log import setup_logging
from src.services.plex import Plex
from src.states import MOVIE_NOTIFY, MOVIE_OPTION
from test_interaction import FakeFaults
from test_log import MAIN, LogFolder


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

# Radarr lookup result for a movie that is in Radarr with its file
DOWNLOADED = {
    "id": 7,
    "title": "Dune",
    "year": 2021,
    "tmdbId": 438631,
    "status": "released",
    "monitored": True,
    "hasFile": True,
    "movieFileId": 31,
}


class MovieTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ A Movie with a fake Radarr, Transmission and Telegram, and its log lines in a temporary folder """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))

        # Logger and functions without Telegram
        self.log = MagicMock()
        self.log.logger = AsyncMock()
        functions = MagicMock()
        functions.sanitize_text = lambda text: text.replace("*", "").replace("_", "")
        functions.send_message = AsyncMock()
        functions.send_image = AsyncMock()
        self.functions = functions
        self.telegram = MagicMock()
        self.telegram.send_admin_message = AsyncMock()
        self.faults = FakeFaults()

        # Movie with a fake Radarr that has room on its disk
        self.movie = Movie(SimpleNamespace(env="dev"), self.log, functions, self.telegram, self.faults)
        self.radarr = MagicMock()
        self.radarr.get_disk_space = AsyncMock(return_value=[{"path": "/media", "freeSpace": 500 * 1024 ** 3}])
        self.radarr.queue_download = AsyncMock(return_value={"id": 1})
        self.radarr.scan_missing_media = AsyncMock()
        self.movie.media_handler = self.radarr
        self.movie.write_to_stats = AsyncMock()
        self.movie.plex.link = AsyncMock(return_value=None)

        # Transmission is up and has no active torrents
        self.transmission = MagicMock()
        self.transmission.return_value.get_active_torrents = AsyncMock(return_value=[])
        for target, value in [
            ("src.commands.media.TransmissionService", self.transmission),
            ("src.commands.media.asyncio.sleep", AsyncMock()),
        ]:
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def update(self, data: str | None = None, text: str | None = None) -> MagicMock:
        """ A button press with this callback_data, or a message with this text, of user 1 """
        update = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_reply_markup = AsyncMock()
        update.callback_query.data = data
        update.message.text = text
        update.effective_user.id = 1
        update.effective_user.first_name = "Test"
        return update

    def context(self, **user_data) -> MagicMock:
        context = MagicMock()
        context.user_data = {
            "label": "film",
            "media_folder": "/media/movies",
            "option_state": MOVIE_OPTION,
            "media_type": "movie",
            "gebruiker": "test",
            **user_data,
        }
        return context

    async def choose(self, lookup: dict, **user_data) -> int:
        """ Lets the user choose the given lookup result as option 1 """
        return await self.movie.media_option(self.update("0"), self.context(media_object=[dict(lookup)], **user_data))

    def admin_messages(self) -> list[str]:
        """ Messages that went to the Beheerder on Telegram """
        return [c.args[0] for c in self.telegram.send_admin_message.await_args_list]


class MovieStateTest(MovieTest):
    """ Checks which route media_option takes for a chosen movie, and the line media_request it writes """

    async def test_new_movie_is_added_to_radarr(self):
        state = await self.choose(NEW_MOVIE)

        self.assertEqual(state, MOVIE_NOTIFY)
        self.radarr.queue_download.assert_awaited_once()
        self.assertEqual(self.radarr.queue_download.await_args.args[0]["tmdbId"], 1001)
        [line] = self.lines("media_request")
        self.assertEqual(line["msg"], "chose option 1: New Movie (2025): download started")
        self.assertEqual((line["level"], line["outcome"], line["option"], line["media_type"]),
                         ("INFO", "download_started", 1, "movie"))
        self.assertEqual((line["media_title"], line["media_year"], line["tmdb_id"]), ("New Movie", 2025, 1001))

    async def test_request_goes_to_the_admin_without_its_text_in_the_log(self):
        await self.choose(NEW_MOVIE)

        [message] = self.admin_messages()
        self.assertIn("User has requested the film New Movie (2025)", message)
        self.log.logger.assert_not_awaited()
        self.assertNotIn("User has requested", self.raw(MAIN))

    async def test_unmonitored_movie_in_radarr_is_not_added_again(self):
        state = await self.choose(IN_RADARR_UNMONITORED)

        self.assertEqual(state, MOVIE_NOTIFY)
        self.radarr.queue_download.assert_not_awaited()
        self.assertTrue(any("marked as unmonitored" in msg for msg in self.admin_messages()))
        [line] = self.lines("media_request")
        self.assertEqual(line["outcome"], "unmonitored")

    async def test_unreleased_unmonitored_movie_in_radarr_is_not_added_again(self):
        state = await self.choose({**IN_RADARR_UNMONITORED, "status": "announced"})

        self.assertEqual(state, MOVIE_NOTIFY)
        self.radarr.queue_download.assert_not_awaited()
        self.assertTrue(any("marked as unmonitored" in msg for msg in self.admin_messages()))
        [line] = self.lines("media_request")
        self.assertEqual(line["outcome"], "unmonitored")

    async def test_unreleased_movie_is_added_to_radarr(self):
        await self.choose({**NEW_MOVIE, "status": "announced"})

        self.radarr.queue_download.assert_awaited_once()
        [line] = self.lines("media_request")
        self.assertEqual(line["outcome"], "not_released")

    async def test_downloaded_movie(self):
        await self.choose(DOWNLOADED)

        [line] = self.lines("media_request")
        self.assertEqual(line["msg"], "chose option 1: Dune (2021): already downloaded")
        self.assertEqual(line["outcome"], "already_downloaded")
        self.assertTrue(any("while it's already downløaded" in msg for msg in self.admin_messages()))

    async def test_downloaded_movie_with_its_link_in_plex(self):
        self.movie.plex.link = AsyncMock(return_value="https://app.plex.tv/desktop/#!/server/id/details?key=7")

        await self.choose(DOWNLOADED)

        self.movie.plex.link.assert_awaited_once_with(DOWNLOADED, "film")
        answer = self.functions.send_message.await_args_list[0].args[0]
        self.assertIn("<a href='https://app.plex.tv/desktop/#!/server/id/details?key=7'>Bekijk Dune in de browser</a>",
                      answer)

    async def test_downloaded_movie_whose_plex_link_fails_gets_the_answer_without_it(self):
        self.enterContext(patch.dict(os.environ, {"PLEX_URL": "http://plex.example.com:32400"}))
        refused = requests.exceptions.ConnectionError("Connection refused")
        self.enterContext(patch("src.services.plex.PlexServer", side_effect=refused))
        self.movie.plex = Plex(self.faults)

        await self.choose(DOWNLOADED)

        [report] = self.faults.reports
        self.assertEqual((report.fault.kind, report.fault.service, report.continued, report.user_told),
                         (FaultKind.DISRUPTION, "plex", "sent the answer without a Plex link", False))
        answer = self.functions.send_message.await_args_list[0].args[0]
        self.assertEqual(answer, "Zo te zien is Dune al gedownløad.")

    async def test_user_hears_there_is_no_space_while_transmission_is_down(self):
        not_responding = Fault.disruption(service="transmission", what="Transmission is not responding")
        self.transmission.return_value.get_active_torrents = AsyncMock(side_effect=not_responding)

        state = await self.choose(NEW_MOVIE)

        # The request goes on, and the download is in Radarr for when Transmission is back
        self.assertEqual(state, MOVIE_NOTIFY)
        self.radarr.queue_download.assert_awaited_once()
        [line] = self.lines("media_request")
        self.assertEqual(line["outcome"], "no_space")
        [report] = self.faults.reports
        self.assertEqual((report.fault, report.continued, report.user_told),
                         (not_responding, "went on without the torrents in Transmission", False))

    async def test_a_download_that_radarr_refuses_falls_through_to_the_wrapper(self):
        refused = Fault.bug(what="Radarr refused the movie request", service="radarr",
                            reason="This movie has already been added", http_status=400)
        self.radarr.queue_download = AsyncMock(side_effect=refused)

        with self.assertRaises(Fault) as caught:
            await self.choose(NEW_MOVIE)

        self.assertIs(caught.exception, refused)
        [line] = self.lines("media_request")
        self.assertEqual((line["msg"], line["outcome"]), ("chose option 1: New Movie (2025): failed", "failed"))
        # The wrapper sends the Foutmelding, and the meldfunctie the one admin message
        self.functions.send_message.assert_not_awaited()
        self.log.logger.assert_not_awaited()
        self.assertEqual(self.admin_messages(), [])

    async def test_a_failed_search_for_missing_movies_is_reported_and_the_request_goes_on(self):
        not_responding = Fault.disruption(service="radarr", what="Radarr is not responding", http_status=503)
        self.radarr.scan_missing_media = AsyncMock(side_effect=not_responding)

        state = await self.choose(NEW_MOVIE)

        self.assertEqual(state, MOVIE_NOTIFY)
        [report] = self.faults.reports
        self.assertEqual((report.fault, report.continued, report.user_told),
                         (not_responding, "went on without the search for missing media", False))
        [line] = self.lines("media_request")
        self.assertEqual(line["outcome"], "download_started")
        first_answer = self.functions.send_message.await_args_list[0].args[0]
        self.assertIn("De downløad voor New Movie is nu gestart", first_answer)

    async def test_no_matching_state_is_a_bug_with_the_fields_the_states_look_at(self):
        # In Radarr, but without a movieFileId
        in_radarr = {"id": 412, "title": "Dune: Part Two", "year": 2024, "tmdbId": 693134, "status": "inCinemas",
                     "monitored": True, "overview": "Paul Atreides unites with Chani"}

        with self.assertRaises(Fault) as caught:
            await self.choose(in_radarr)

        fault = caught.exception
        self.assertEqual((fault.kind, fault.what), (FaultKind.BUG, "No media state matched"))
        self.assertEqual(fault.details, {"id": 412, "movieFileId": None, "monitored": True, "status": "inCinemas"})
        [line] = self.lines("media_request")
        self.assertEqual((line["msg"], line["outcome"]), ("chose option 1: Dune: Part Two (2024): failed", "failed"))
        self.functions.send_message.assert_not_awaited()
        self.log.logger.assert_not_awaited()
        self.assertEqual(self.admin_messages(), [])

    async def test_a_movie_without_a_tmdbId_falls_through_to_the_wrapper(self):
        without_id = {key: value for key, value in NEW_MOVIE.items() if key != "tmdbId"}

        with self.assertRaises(KeyError):
            await self.choose(without_id)

        [line] = self.lines("media_request")
        self.assertEqual(line["outcome"], "failed")
        self.functions.send_message.assert_not_awaited()
        self.log.logger.assert_not_awaited()

    async def test_stats_that_cannot_be_written_are_reported_and_the_request_goes_on(self):
        del self.movie.write_to_stats
        self.movie.stats_json = str(self.folder / "stats.dev.json")

        state = await self.choose(NEW_MOVIE)

        self.assertEqual(state, MOVIE_NOTIFY)
        [report] = self.faults.reports
        self.assertEqual((report.fault.kind, report.fault.what, report.continued, report.user_told),
                         (FaultKind.BUG, "Could not write the request to stats.json",
                          "went on without counting the request", False))
        self.assertIsInstance(report.fault.__cause__, FileNotFoundError)
        self.log.logger.assert_not_awaited()

    async def test_no_disk_with_room_is_an_inrichtingsfout(self):
        self.radarr.get_disk_space = AsyncMock(return_value=[{"path": "/media", "freeSpace": 100 * 1024 ** 3}])

        with self.assertRaises(Fault) as caught:
            await self.choose(NEW_MOVIE)

        fault = caught.exception
        self.assertEqual((fault.kind, fault.service, fault.check, fault.item, fault.what),
                         (FaultKind.SETUP, "radarr", "disk_space", None, "No disk of Radarr has 150 GB free"))
        self.assertEqual(fault.details, {"/media": "100 GB free"})
        self.assertEqual(fault.user_text, "Er is op dit moment een probleem met de opslag van de Plęx server")
        self.radarr.queue_download.assert_not_awaited()
        [line] = self.lines("media_request")
        self.assertEqual(line["outcome"], "failed")
        # The wrapper tells the user, with the Code
        self.functions.send_message.assert_not_awaited()
        self.log.logger.assert_not_awaited()

    async def test_a_disk_with_room_passes_both_checks(self):
        await self.choose(NEW_MOVIE)

        self.assertEqual([(fix.service, fix.check, fix.item, fix.msg) for fix in self.faults.fixes], [
            ("radarr", "setting", "MOVIE_FOLDERS", "Every folder in MOVIE_FOLDERS is on a disk of Radarr"),
            ("radarr", "disk_space", None, "A disk of Radarr has 150 GB free again"),
        ])
        self.assertEqual(self.faults.reports, [])

    async def test_a_media_folder_on_no_disk_is_reported_and_the_other_folders_are_tried(self):
        state = await self.choose(NEW_MOVIE, media_folder="/elsewhere/movies, /media/movies")

        self.assertEqual(state, MOVIE_NOTIFY)
        self.assertEqual(self.radarr.queue_download.await_args.args[0]["rootFolderPath"], "/media/movies")
        [report] = self.faults.reports
        fault = report.fault
        self.assertEqual((fault.kind, fault.service, fault.check, fault.item, fault.what),
                         (FaultKind.SETUP, "radarr", "setting", "MOVIE_FOLDERS",
                          "MOVIE_FOLDERS has a folder on no disk of Radarr"))
        self.assertEqual(fault.details, {"folders": ["/elsewhere/movies"], "disks": ["/media"]})
        self.assertEqual(report.continued, "looked for room in the other folders")
        self.assertNotIn("setting", [fix.check for fix in self.faults.fixes])

    async def test_media_folders_on_no_disk_at_all_are_an_inrichtingsfout_of_the_setting(self):
        for folders in ("/elsewhere/movies", None):
            with self.subTest(folders=folders):
                with self.assertRaises(Fault) as caught:
                    await self.choose(NEW_MOVIE, media_folder=folders)

                fault = caught.exception
                self.assertEqual((fault.kind, fault.check, fault.item), (FaultKind.SETUP, "setting", "MOVIE_FOLDERS"))
                self.radarr.queue_download.assert_not_awaited()
                self.assertEqual(self.faults.reports, [])

    async def test_title_in_the_lines_is_the_title_of_radarr(self):
        # The title is sanitized for the MarkdownV2 of the answers, but not for the log, also not in the next step
        context = self.context(media_object=[{**NEW_MOVIE, "title": "*batteries not included"}])

        await self.movie.media_option(self.update("0"), context)
        await self.movie.stay_notified(self.update("film_notify_no"), context)

        self.assertEqual([line["media_title"] for line in self.lines("media_request") + self.lines("notify_choice")],
                         ["*batteries not included", "*batteries not included"])
        self.assertEqual(context.user_data["media_data"]["title"], "batteries not included")

    async def test_unmonitor_flag_of_an_earlier_big_serie_is_not_used(self):
        # A serie with more than 5 seasons sets set_monitored to False. The persisted user_data kept
        # it, so every later movie of that Gebruiker was added unmonitored and never searched.
        await self.choose(NEW_MOVIE, set_monitored=False)

        self.radarr.queue_download.assert_awaited_once()
        self.assertTrue(self.radarr.queue_download.await_args.args[0]["monitored"])


class MovieSearchTest(MovieTest):
    """ The lines of the steps before and after the choice of a movie """

    async def test_search_term_as_typed_with_the_number_of_results(self):
        self.radarr.lookup_by_name = AsyncMock(return_value=[NEW_MOVIE, IN_RADARR_UNMONITORED])

        await self.movie.request_media(self.update(text="kpop *demon* hunters"), self.context())

        [line] = self.lines("search_term")
        self.assertEqual(line["msg"], "searched 'kpop *demon* hunters' for movie: 2 results")
        self.assertEqual((line["query"], line["media_type"], line["results"]), ("kpop *demon* hunters", "movie", 2))
        self.assertNotIn("purpose", line)

    async def test_search_term_without_results(self):
        self.radarr.lookup_by_name = AsyncMock(return_value=[])

        await self.movie.request_media(self.update(text="kpop demon huntres"), self.context())

        [line] = self.lines("search_term")
        self.assertEqual((line["msg"], line["results"]), ("searched 'kpop demon huntres' for movie: 0 results", 0))

    async def test_search_buttons(self):
        context = self.context(media_object=[NEW_MOVIE] * 7, requested_media="new movie", options_shown=5)

        await self.movie.media_show_more(self.update("more"), context)
        await self.movie.request_media_again(self.update("retry"), context)
        await self.movie.request_media_again(self.update("no"), context)

        self.assertEqual([(line["msg"], line["button"]) for line in self.lines("search_button")], [
            ("pressed 'show more'", "more"),
            ("pressed 'try again'", "retry"),
            ("try again after no results: no", "no"),
        ])

    async def test_notify_choice(self):
        context = self.context(media_data=dict(DOWNLOADED))

        await self.movie.stay_notified(self.update("film_notify_no"), context)

        [line] = self.lines("notify_choice")
        self.assertEqual(line["msg"], "notify when Dune (2021) is online: no")
        self.assertEqual((line["choice"], line["tmdb_id"]), ("no", 438631))

    async def test_quality_request_with_a_description(self):
        context = self.context(media_data=dict(DOWNLOADED))

        await self.movie.media_upgrade(self.update("film_upgrade_yes"), context)
        await self.movie.media_upgrade_info(self.update("other"), context)
        await self.movie.media_upgrade_info_other(self.update(text="the audio is *Russian*"), context)

        self.assertEqual([(line["msg"], line.get("choice"), line.get("reason"), line.get("text"))
                          for line in self.lines("quality_request")], [
            ("something wrong with the download of Dune (2021): yes", "yes", None, None),
            ("quality request for Dune (2021): other", None, "other", None),
            ("quality request for Dune (2021): other: 'the audio is *Russian*'", None, "other", "the audio is *Russian*"),
        ])
        [message] = self.admin_messages()
        self.assertIn("User did a quality request for Dune", message)
        self.assertNotIn("User did a quality request", self.raw(MAIN))


if __name__ == "__main__":
    unittest.main()
