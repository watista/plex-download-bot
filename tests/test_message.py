#!/usr/bin/python3

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.ext import ConversationHandler

from src.commands.message import Message
from src.log import setup_logging
from src.states import ADD_MOVIE, ADD_MOVIE_USER, MESSAGE_ID, MESSAGE_MESSAGE
from src.telegram_out import DELIVERED, Delivery
from test_conversation import message, press
from test_log import MAIN, LogFolder


class MessageTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ General updates on and off, and the admin commands /message, /message_all and /add_movie """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))
        self.enterContext(patch("src.commands.message.asyncio.sleep", AsyncMock()))

        # Logger and functions without Telegram; user 3 has blocked the bot
        self.log = MagicMock()
        self.log.logger = AsyncMock()
        self.functions = MagicMock(send_message=AsyncMock(), format_admin_broadcast_html=lambda text: text)
        self.telegram = MagicMock(send_user_message=AsyncMock(
            side_effect=lambda user_id, kind, text: Delivery("Forbidden: bot was blocked by the user")
            if user_id == 3 else DELIVERED))

        # User 2 turned general updates off
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_json = Path(tmp.name) / "data.json"
        self.data_json.write_text(json.dumps({
            "user_id": {"1": "wouter, Wouter", "2": "anna, Anna", "3": "piet, Piet"},
            "update_messages": {"2": False}, "notify_list": {"555": {"film": {}}}}))
        self.message = Message(SimpleNamespace(env="live"), self.log, self.functions, self.telegram)
        self.message.data_json = str(self.data_json)

    async def test_general_updates_on_while_they_are_on(self):
        state = await self.message.updates_subscribe(message("/aanmelden_updates"), MagicMock(user_data={}))

        self.assertEqual(state, ConversationHandler.END)
        command, updates = self.read(MAIN)
        self.assertEqual(command["msg"], "command /aanmelden_updates")
        self.assertEqual((updates["event"], updates["msg"], updates["choice"], updates["outcome"]),
                         ("general_updates", "general updates on: already on", "on", "unchanged"))

    async def test_general_updates_off_in_the_start_menu(self):
        await self.message.updates_unsubscribe(press("afmelden_updates"), MagicMock(user_data={}))

        choice, updates = self.read(MAIN)
        self.assertEqual(choice["msg"], "chose 'general updates off' in the start menu")
        self.assertEqual((updates["msg"], updates["choice"], updates["outcome"]),
                         ("general updates off: changed", "off", "changed"))
        self.assertIs(json.loads(self.data_json.read_text())["update_messages"]["1"], False)

    async def test_message_to_one_user(self):
        context = MagicMock(user_data={})

        states = [await self.message.message_start(message("/message"), context),
                  await self.message.message_id(message("twelve"), context),
                  await self.message.message_id(message("555"), context),
                  await self.message.message_send(message("Plex is _even_ offline"), context)]

        self.assertEqual(states, [MESSAGE_ID, MESSAGE_ID, MESSAGE_MESSAGE, ConversationHandler.END])
        lines = self.lines("admin_command")
        self.assertEqual([line["msg"] for line in lines], [
            "admin command /message",
            "/message: the recipient is not a number",
            "/message: recipient 555",
            "/message to 555: 'Plex is _even_ offline'",
        ])
        self.assertEqual({line["command"] for line in lines}, {"/message"})
        self.assertEqual(lines[1]["outcome"], "not_a_number")
        self.assertNotIn("twelve", self.raw(MAIN))
        self.assertEqual((lines[3]["recipient"], lines[3]["text"]), (555, "Plex is _even_ offline"))

    async def test_message_to_everyone_counts_who_got_it(self):
        context = MagicMock(user_data={})

        await self.message.message_all(message("/message_all"), context)
        state = await self.message.message_all_id(message("Nieuwe schijf!"), context)

        self.assertEqual(state, ConversationHandler.END)
        start, sent = self.lines("admin_command")
        self.assertEqual((start["msg"], start["command"]), ("admin command /message_all", "/message_all"))
        self.assertEqual(sent["msg"], "/message_all: 'Nieuwe schijf!': sent 1, not delivered 1, skipped 1")
        self.assertEqual((sent["text"], sent["sent"], sent["not_delivered"], sent["skipped"]),
                         ("Nieuwe schijf!", 1, 1, 1))

    async def test_add_a_movie_for_a_user(self):
        context = MagicMock(user_data={})

        states = [await self.message.add_movie(message("/add_movie"), context),
                  await self.message.add_movie_user(message("555"), context),
                  await self.message.add_movie_id(message("dune"), context),
                  await self.message.add_movie_id(message("438631"), context)]

        self.assertEqual(states, [ADD_MOVIE, ADD_MOVIE_USER, ADD_MOVIE_USER, ConversationHandler.END])
        lines = self.lines("admin_command")
        self.assertEqual([line["msg"] for line in lines], [
            "admin command /add_movie",
            "/add_movie: recipient 555",
            "/add_movie: the tmdbId is not a number",
            "/add_movie: tmdb 438631 for 555",
        ])
        self.assertEqual((lines[3]["recipient"], lines[3]["tmdb_id"]), (555, 438631))
        self.log.logger.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
