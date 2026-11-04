#!/usr/bin/python3

import json
import logging
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from src.interaction import InteractionProcessor, current_code
from src.log import get_logger, setup_logging
from src.log.search import Position, Query, from_library, search
from test_interaction import message_from
from test_log import LogFolder


def line(ts: str, msg: str, **fields) -> dict:
    """ A line of the bot as the main file has it, at this moment of 2026-11 in Dutch local time """
    return {"ts": f"2026-11-{ts}+01:00", "level": "INFO", **fields, "msg": msg, "logger": "commands.media",
            "src": "src/commands/media.py:60 in search"}


def library_line(ts: str, msg: str, **fields) -> dict:
    """ A line of a library, with the context of the Interaction it was written in """
    return {"ts": f"2026-11-{ts}+01:00", "level": "WARNING", **fields, "msg": msg, "logger": "httpx",
            "src": "env/lib/python3.12/site-packages/httpx/_client.py:1025 in _send_single_request"}


class LogFiles:
    """ A temporary log folder to write day files of dev in """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def write(self, day: str, *lines: dict | str, name: str | None = None) -> Path:
        """ Adds lines to the main file of this day; a str is written as it is, like a half line """
        path = self.folder / (name or f"dev-plex-download-bot-{day}.jsonl")
        with path.open("a", encoding="utf-8") as file:
            for item in lines:
                file.write(item if isinstance(item, str) else json.dumps(item, ensure_ascii=False) + "\n")
        return path

    async def search(self, query: Query, before: Position | None = None, after: Position | None = None) -> list:
        return [found async for found in search(str(self.folder), "dev", query, before=before, after=after)]

    async def msgs(self, query: Query, before: Position | None = None, after: Position | None = None) -> list[str]:
        return [found.line["msg"] for found in await self.search(query, before, after)]


class SearchTest(LogFiles, unittest.IsolatedAsyncioTestCase):
    """ The Loglezer: the lines of a person or a Code, from new to old, over the day files of the folder """

    def setUp(self):
        super().setUp()
        self.write("2026-11-01",
                   line("01T09:00:00.000", "command /start", user_id=1, account="wouter"),
                   line("01T09:01:00.000", "command /start", user_id=2, account="anna"),
                   line("01T09:02:00.000", "menu choice: movie", user_id=1, account="wouter"))
        self.write("2026-11-03",
                   line("03T14:05:00.000", "searched 'dune' for movie: 7 results", user_id=1, account="wouter"),
                   line("03T14:06:00.000", "chose option 3: Dune (2021)", user_id=1, account="wouter"))

        # Neither the debug file nor an old .log file is read
        self.write("", line("03T14:05:30.000", "debug only", user_id=1), name="dev-plex-download-bot-2026-11-03-debug.jsonl")
        self.write("", "command /start of wouter\n", name="dev-plex-download-bot-2026-10-30.log")
        # Nor the files of live
        self.write("", line("02T10:00:00.000", "live", user_id=1), name="plex-download-bot-2026-11-02.jsonl")

    async def test_the_lines_of_a_user_id_from_new_to_old_over_several_days(self):
        self.assertEqual(await self.msgs(Query(user_ids=frozenset({1}))), [
            "chose option 3: Dune (2021)",
            "searched 'dune' for movie: 7 results",
            "menu choice: movie",
            "command /start",
        ])

    async def test_each_line_has_the_day_of_its_file_and_the_byte_offset_where_it_starts(self):
        found = await self.search(Query(user_ids=frozenset({1})))

        self.assertEqual([item.position.day for item in found],
                         [date(2026, 11, 3), date(2026, 11, 3), date(2026, 11, 1), date(2026, 11, 1)])
        for item in found:
            path = self.folder / f"dev-plex-download-bot-{item.position.day.isoformat()}.jsonl"
            with path.open("rb") as file:
                file.seek(item.position.offset)
                self.assertEqual(json.loads(file.readline()), item.line)

    async def test_a_half_last_line_that_the_bot_is_still_writing_is_skipped(self):
        self.write("2026-11-03", json.dumps(line("03T14:07:00.000", "chose 'yes'", user_id=1))[:60])

        self.assertEqual((await self.msgs(Query(user_ids=frozenset({1}))))[0], "chose option 3: Dune (2021)")

    async def test_the_same_lines_when_read_in_blocks_smaller_than_a_line(self):
        self.write("2026-11-03", json.dumps(line("03T14:07:00.000", "chose 'yes'", user_id=1))[:60])
        everything = await self.msgs(Query(user_ids=frozenset({1})))

        for block in (1, 7, 64, 150):
            with self.subTest(block=block), patch("src.log.search.BLOCK", block):
                self.assertEqual(await self.msgs(Query(user_ids=frozenset({1}))), everything)

    async def test_a_user_id_only_finds_itself_and_not_a_longer_one(self):
        self.write("2026-11-03", line("03T15:00:00.000", "command /help", user_id=11, account="kees"))

        self.assertNotIn("command /help", await self.msgs(Query(user_ids=frozenset({1}))))

    async def test_a_shared_account_with_its_bezoeker_lines_and_a_name_only_in_the_logs(self):
        self.write("2026-11-02",
                   # Before the login, as a Bezoeker
                   line("02T08:00:00.000", "login: ok", user_id=3, tg_name="Sanne"),
                   # Two persons under one account, also written in another case
                   line("02T08:01:00.000", "command /start", user_id=3, account="Wouter"),
                   line("02T08:02:00.000", "command /help", user_id=1, account="wouter"),
                   # An old user ID of wouter, no longer in the user list
                   line("02T08:03:00.000", "command /stop", user_id=4, account="wouter"),
                   # Someone else
                   line("02T08:04:00.000", "command /start", user_id=2, account="anna"))

        msgs = await self.msgs(Query(user_ids=frozenset({1, 3}), account="wouter"), after=None,
                               before=Position(date(2026, 11, 3), 0))

        self.assertEqual(msgs, ["command /stop", "command /help", "command /start", "login: ok",
                                "menu choice: movie", "command /start"])

    async def test_an_account_name_is_found_in_any_case_also_with_letters_outside_ascii(self):
        self.write("2026-11-02",
                   line("02T08:00:00.000", "command /start", user_id=7, account="Émile"),
                   line("02T08:01:00.000", "command /help", user_id=8, account="Strasse"),
                   line("02T08:02:00.000", "searched 'Amélie'", user_id=9, account="Kees"))

        self.assertEqual(await self.msgs(Query(account="émile")), ["command /start"])
        self.assertEqual(await self.msgs(Query(account="ÉMILE")), ["command /start"])
        self.assertEqual(await self.msgs(Query(account="STRAßE")), ["command /help"])
        self.assertEqual(await self.msgs(Query(account="kees")), ["searched 'Amélie'"])

    async def test_only_the_lines_before_a_position(self):
        newest, second, *_ = await self.search(Query(user_ids=frozenset({1})))

        self.assertEqual(await self.msgs(Query(user_ids=frozenset({1})), before=second.position),
                         ["menu choice: movie", "command /start"])
        self.assertEqual(await self.msgs(Query(user_ids=frozenset({1})), before=newest.position),
                         ["searched 'dune' for movie: 7 results", "menu choice: movie", "command /start"])

    async def test_only_the_lines_after_a_position(self):
        *_, second_oldest, oldest = await self.search(Query(user_ids=frozenset({1})))

        self.assertEqual(await self.msgs(Query(user_ids=frozenset({1})), after=second_oldest.position),
                         ["chose option 3: Dune (2021)", "searched 'dune' for movie: 7 results"])
        self.assertEqual(await self.msgs(Query(user_ids=frozenset({1})), after=oldest.position),
                         ["chose option 3: Dune (2021)", "searched 'dune' for movie: 7 results",
                          "menu choice: movie"])

    async def test_the_lines_of_a_code_also_over_midnight(self):
        self.write("2026-11-01", line("01T23:59:59.900", "check_notify_list started", interaction_id="k7p2qx",
                                      job="check_notify_list"))
        self.write("2026-11-02",
                   line("02T00:00:00.100", "sent user message online", user_id=1, account="wouter",
                        interaction_id="k7p2qx", job="check_notify_list"),
                   line("02T00:00:00.200", "check_notify_list finished in 0.3 s", interaction_id="k7p2qx",
                        job="check_notify_list"),
                   line("02T00:30:00.000", "check_notify_list finished in 0.2 s", interaction_id="m3tq8w",
                        job="check_notify_list"))

        self.assertEqual(await self.msgs(Query(code="k7p2qx")), [
            "check_notify_list finished in 0.3 s", "sent user message online", "check_notify_list started"])

    async def test_a_code_stops_at_the_first_older_file_without_it(self):
        # The same code a year back is another Interaction: it is never reached
        self.write("2026-11-02", line("02T10:00:00.000", "command /start", user_id=1, interaction_id="k7p2qx"))
        self.write("2025-11-02", line("02T10:00:00.000", "command /help", user_id=1, interaction_id="k7p2qx"))

        self.assertEqual(await self.msgs(Query(code="k7p2qx")), ["command /start"])

    async def test_lines_that_are_not_json_are_skipped(self):
        self.write("2026-11-03", '{"user_id": 1, "msg": broken\n', "\n", '[{"user_id": 1}]\n')

        self.assertEqual(len(await self.msgs(Query(user_ids=frozenset({1})))), 4)

    async def test_without_files_nothing_is_found(self):
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)

        self.assertEqual([found async for found in search(empty.name, "dev", Query(user_ids=frozenset({1})))], [])


class WrittenByTheBotTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ The lines as the bot itself writes them, in an Interaction of a Gebruiker """

    async def test_found_by_user_id_account_name_and_code(self):
        setup_logging("dev", "INFO", str(self.folder), False)
        codes = []

        async def account_for(user_id: int) -> str:
            return "Émile"

        async def handle() -> None:
            codes.append(current_code())
            get_logger("src.commands.media").info("searched 'dune' for movie: 7 results", event="search_term",
                                                  query="dune", media_type="movie", results=7)
            logging.getLogger("httpx").warning("HTTP Request: GET https://radarr/api/v3/movie/lookup failed")

        with self.at("2026-11-03T14:05:12+01:00"):
            await InteractionProcessor(1, account_for).do_process_update(message_from(123456789, "Emile"), handle())

        for query in (Query(user_ids=frozenset({123456789})), Query(account="ÉMILE"), Query(code=codes[0])):
            with self.subTest(query=query):
                found = [found async for found in search(str(self.folder), "dev", query)]
                self.assertEqual([item.line["msg"] for item in found], [
                    "HTTP Request: GET https://radarr/api/v3/movie/lookup failed",
                    "searched 'dune' for movie: 7 results",
                ])
                self.assertEqual([from_library(item.line) for item in found], [True, False])


class FromLibraryTest(unittest.TestCase):
    """ Which lines are of a library: the logger of the line is not one of the bot """

    def test_own_lines(self):
        self.assertFalse(from_library(line("03T14:05:00.000", "command /start")))
        for logger in ("bot", "commands.media", "services.request", "log", "src", "__main__"):
            with self.subTest(logger=logger):
                self.assertFalse(from_library({"logger": logger}))
        # A Fout or an event is always of the bot
        self.assertFalse(from_library({"fault": "bug", "logger": "telegram.ext.Application"}))
        self.assertFalse(from_library({"event": "bot_crashed"}))

    def test_library_lines(self):
        self.assertTrue(from_library(library_line("03T14:05:00.000", "HTTP Request: GET")))
        for logger in ("telegram.ext.Application", "apscheduler.scheduler", "py.warnings", "transmission-rpc",
                       "commands.unknown", "..", ""):
            with self.subTest(logger=logger):
                self.assertTrue(from_library({"logger": logger}))
        self.assertTrue(from_library({}))


if __name__ == "__main__":
    unittest.main()
