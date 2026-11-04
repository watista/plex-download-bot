#!/usr/bin/python3

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.ext import ConversationHandler

from src.commands.maintenance import Maintenance
from src.commands.start import Start
from src.faults import Fault, FaultKind
from src.log import setup_logging
from src.states import REQUEST_ACCOUNT, REQUEST_MOVIE, VERIFY, VERIFY_PWD
from test_conversation import message, press
from test_log import MAIN, LogFolder


# The password of the account wouter
PASSWORD = "hunter2"


class StartTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ The start of a Gesprek: /start, text outside a Gesprek, the start menu and the login """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))

        # Logger and functions without Telegram
        self.log = MagicMock()
        self.log.logger = AsyncMock()
        self.functions = MagicMock(send_message=AsyncMock(), send_gif=AsyncMock())
        self.telegram = MagicMock(send_admin_message=AsyncMock())
        self.maintenance = MagicMock(notice=AsyncMock(return_value=ConversationHandler.END))
        self.enterContext(patch("src.commands.start.asyncio.sleep", AsyncMock()))
        self.enterContext(patch("src.commands.start.open", MagicMock(), create=True))

        # User 1 is the Gebruiker wouter, user 666 is blocked, user 777 a Bezoeker
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_json = Path(tmp.name) / "data.dev.json"
        self.data_json.write_text(json.dumps({
            "users": {"wouter": PASSWORD}, "user_id": {"1": "wouter, Wouter"}, "blocked_users": {"666": "Mallory"},
            "notify_list": {}, "update_messages": {}}))
        self.stats_json = Path(tmp.name) / "stats.dev.json"
        self.stats_json.write_text("{}")

    def start(self, mode: str = "normal") -> Start:
        """ Start in this mode, on the data.json and stats.json of the test """
        start = Start(SimpleNamespace(env="dev", mode=mode), self.log, self.functions, self.maintenance, self.telegram)
        start.data_json, start.stats_json = str(self.data_json), str(self.stats_json)
        start.subscribe = MagicMock(afmelden=AsyncMock(return_value=ConversationHandler.END))
        return start

    def admin_messages(self) -> list[str]:
        """ What send_admin_message said each message was about """
        return [call.args[1] for call in self.telegram.send_admin_message.await_args_list]

    async def test_start_shows_the_menu(self):
        state = await self.start().start_msg(message("/start"), MagicMock(user_data={}))

        self.assertEqual(state, VERIFY)
        [line] = self.read(MAIN)
        self.assertEqual((line["event"], line["msg"], line["command"]), ("command", "command /start", "/start"))
        # The handler writes the line, not the module that describes it
        self.assertEqual(line["logger"], "commands.start")
        self.assertTrue(line["src"].endswith(" in start_msg"), line["src"])

    async def test_text_outside_a_conversation_shows_the_menu_without_the_text(self):
        state = await self.start().outside_conversation(message(PASSWORD, 777, "Sanne"), MagicMock(user_data={}))

        self.assertEqual(state, VERIFY)
        self.functions.send_gif.assert_awaited_once()
        [line] = self.read(MAIN)
        self.assertEqual((line["event"], line["msg"], line["outcome"]),
                         ("outside_conversation", "sent text outside a conversation: showed /start", "start_shown"))
        self.assertNotIn(PASSWORD, self.raw(MAIN))

    async def test_a_gebruiker_chooses_movie_in_the_start_menu(self):
        state = await self.start().verification(press("movie_request"), MagicMock(user_data={}))

        self.assertEqual(state, REQUEST_MOVIE)
        [line] = self.read(MAIN)
        self.assertEqual(line["msg"], "chose 'movie' in the start menu")
        self.assertEqual((line["event"], line["menu"], line["button"]), ("menu_choice", "start", "movie_request"))
        self.assertNotIn("outcome", line)

    async def test_a_command_that_needs_a_login(self):
        await self.start().verification(message("/afmelden_serie"), MagicMock(user_data={}))

        [line] = self.lines("command")
        self.assertEqual((line["msg"], line["command"]), ("command /afmelden_serie", "/afmelden_serie"))

    async def test_in_maintenance_mode_a_gebruiker_gets_the_maintenance_message(self):
        state = await self.start("maintenance").verification(press("serie_request"), MagicMock(user_data={}))

        self.assertEqual(state, ConversationHandler.END)
        self.maintenance.notice.assert_awaited_once()
        [line] = self.read(MAIN)
        self.assertEqual(line["msg"], "chose 'series' in the start menu: maintenance message")
        self.assertEqual((line["event"], line["outcome"]), ("menu_choice", "maintenance"))

    async def test_in_maintenance_mode_a_command_for_series_updates_gets_the_maintenance_message(self):
        state = await Maintenance(self.log, self.functions).media_maintenance(message("/aanmelden_serie"),
                                                                              MagicMock(user_data={}))

        self.assertEqual(state, ConversationHandler.END)
        self.functions.send_message.assert_awaited_once()
        [line] = self.read(MAIN)
        self.assertEqual(line["msg"], "command /aanmelden_serie: maintenance message")
        self.assertEqual((line["event"], line["command"], line["outcome"]),
                         ("command", "/aanmelden_serie", "maintenance"))
        self.log.logger.assert_not_awaited()

    async def test_in_maintenance_mode_a_new_account_can_still_be_requested(self):
        state = await self.start("maintenance").account_request(press("account_request"), MagicMock(user_data={}))

        self.assertEqual(state, REQUEST_ACCOUNT)
        [line] = self.read(MAIN)
        self.assertEqual(line["msg"], "chose 'new account' in the start menu")
        self.assertNotIn("outcome", line)

    async def test_a_blocked_bezoeker_is_refused(self):
        state = await self.start().verification(press("movie_request", 666, "Mallory"), MagicMock(user_data={}))

        self.assertEqual(state, ConversationHandler.END)
        choice, login = self.read(MAIN)
        self.assertEqual(choice["event"], "menu_choice")
        self.assertEqual((login["event"], login["msg"], login["outcome"]),
                         ("login", "login refused: on the blocklist", "refused"))
        self.assertEqual(self.admin_messages(), ["blocked user tried to log in"])
        self.log.logger.assert_not_awaited()

    async def test_a_bezoeker_is_asked_for_the_password(self):
        context = MagicMock(user_data={})

        state = await self.start().verification(press("movie_request", 777, "Sanne"), context)

        self.assertEqual(state, VERIFY_PWD)
        self.assertEqual(context.user_data["login_tries"], 0)
        self.assertEqual([line["event"] for line in self.read(MAIN)], ["menu_choice"])

    async def test_a_login(self):
        context = MagicMock(user_data={"media_option": "movie_request", "login_tries": 0})

        state = await self.start().verify_pwd(message(PASSWORD, 777, "Sanne"), context)

        self.assertEqual(state, REQUEST_MOVIE)
        [line] = self.lines("login")
        self.assertEqual((line["msg"], line["outcome"], line["logged_in_as"]),
                         ("logged in as wouter", "success", "wouter"))
        self.assertNotIn("maintenance", line)
        self.assertEqual(self.admin_messages(), ["first login"])
        self.assertNotIn(PASSWORD, self.raw(MAIN))
        self.log.logger.assert_not_awaited()

    async def test_in_maintenance_mode_a_login_ends_with_the_maintenance_message(self):
        context = MagicMock(user_data={"media_option": "serie_request", "login_tries": 0})

        state = await self.start("maintenance").verify_pwd(message(PASSWORD, 777, "Sanne"), context)

        self.assertEqual(state, ConversationHandler.END)
        self.maintenance.notice.assert_awaited_once()
        [line] = self.lines("login")
        self.assertEqual((line["msg"], line["outcome"], line["maintenance"]),
                         ("logged in as wouter: maintenance message", "success", True))

    async def test_a_wrong_password_three_times(self):
        context = MagicMock(user_data={"media_option": "movie_request", "login_tries": 0})
        start = self.start()

        states = [await start.verify_pwd(message(f"wrong-{n}", 777, "Sanne"), context) for n in (1, 2, 3)]

        self.assertEqual(states, [VERIFY_PWD, VERIFY_PWD, ConversationHandler.END])
        lines = self.lines("login")
        self.assertEqual([line["msg"] for line in lines], [
            "wrong password (attempt 1 of 3)",
            "wrong password (attempt 2 of 3)",
            "wrong password (attempt 3 of 3): blocked",
        ])
        self.assertEqual([(line["outcome"], line["attempt"]) for line in lines],
                         [("wrong_password", 1), ("wrong_password", 2), ("blocked", 3)])
        self.assertEqual(self.admin_messages(), ["user blocked"])
        self.assertIn("777", json.loads(self.data_json.read_text())["blocked_users"])
        self.assertNotIn("wrong-", self.raw(MAIN))

    async def test_an_unknown_request_type_is_a_bug(self):
        context = MagicMock(user_data={"media_option": "film_request", "login_tries": 0})

        with self.assertRaises(Fault) as caught:
            await self.start().parse_request(message(PASSWORD), context)

        fault = caught.exception
        self.assertEqual((fault.kind, fault.what, fault.details),
                         (FaultKind.BUG, "Unknown request type", {"media_option": "film_request"}))
        self.functions.send_message.assert_not_awaited()
        self.log.logger.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
