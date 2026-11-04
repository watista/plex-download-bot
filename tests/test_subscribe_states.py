#!/usr/bin/python3

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import CallbackQuery, Chat, Message, Update, User
from telegram.ext import ConversationHandler

from src.bot import Bot
from src.commands.subscribe import Subscribe
from src.log import setup_logging
from src.states import AANMELD_CHOICE, AFMELDEN_OPTIE, REQUEST_SERIE
from test_log import LogFolder


# The Gebruiker gets new episodes of Game of Thrones (tmdbId 1399)
SUBSCRIBED = {"1399": {"started": True, "last": "S08E06"}}

# Sonarr lookup result for a serie that is downløaded and still running
THE_BEAR = {"title": "The Bear", "year": 2022, "tmdbId": 136315, "path": "/media/series/The Bear"}


class SubscribeStateTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ Checks which handler gets a button that is pressed while the bot waits for a serie choice """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))

        # Logger and functions without Telegram
        self.log = MagicMock()
        self.log.logger = AsyncMock()
        functions = MagicMock()
        functions.sanitize_text = lambda text: text
        functions.send_message = AsyncMock()
        functions.send_image = AsyncMock()
        self.telegram = MagicMock()
        self.telegram.send_admin_message = AsyncMock()

        # Subscribe with a fake Sonarr and its own data.json
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_json = Path(tmp.name) / "data.dev.json"
        self.data_json.write_text(json.dumps({"notify_list": {"1": {"serie_episode": dict(SUBSCRIBED)}}}))
        self.subscribe = Subscribe(SimpleNamespace(env="dev"), self.log, functions, self.telegram)
        self.subscribe.data_json = str(self.data_json)
        self.sonarr = MagicMock()
        self.sonarr.lookup_by_tmdbid = AsyncMock(
            return_value=[{"title": "Game of Thrones", "year": 2011, "tmdbId": 1399}])
        self.subscribe.sonarr = self.sonarr
        patcher = patch("src.commands.subscribe.asyncio.sleep", AsyncMock())
        patcher.start()
        self.addCleanup(patcher.stop)

        # Bot with only what its conversation handler needs, the welcome buttons start a fake Serie flow
        bot = Bot.__new__(Bot)
        for name in ("start", "help", "message", "account", "movie", "serie"):
            setattr(bot, name, MagicMock())
        bot.start.verification = AsyncMock(return_value=REQUEST_SERIE)
        bot.subscribe = self.subscribe
        bot.allowed_users = [1]
        bot.account_for = AsyncMock(return_value="test")
        self.verification = bot.start.verification
        self.conversation = bot._build_normal_conversation()

    async def press(self, data: str, state: int, **user_data):
        """ Presses the button with this callback_data while the conversation of user 1 is in this state """

        chat = Chat(id=1, type=Chat.PRIVATE)
        user = User(id=1, first_name="Test", is_bot=False)
        query = CallbackQuery(id="1", from_user=user, chat_instance="1", data=data,
                              message=Message(message_id=1, date=datetime.now(), chat=chat))
        telegram_bot = MagicMock()
        telegram_bot.answer_callback_query = AsyncMock()
        query.set_bot(telegram_bot)
        update = Update(update_id=1, callback_query=query)

        # Let PTB choose the handler, first those of the state and then the fallbacks
        self.conversation._conversations[(chat.id, user.id)] = state
        _, _, handler, _ = self.conversation.check_update(update)

        context = MagicMock()
        context.user_data = {"gebruiker": "test", **user_data}
        return await handler.callback(update, context)

    def subscribed(self) -> dict:
        """ The series in data.json that user 1 gets new episodes of """
        return json.loads(self.data_json.read_text())["notify_list"]["1"]["serie_episode"]

    async def test_serie_button_while_choosing_a_serie_to_unsubscribe_from(self):
        # On 01-10-2026 the live bot looked up a serie with TMDB ID "serie_request". That is the
        # 📺 Serie button of an earlier /start message, pressed while the bot waited for a serie
        # to unsubscribe from.
        state = await self.press("serie_request", AFMELDEN_OPTIE)

        self.sonarr.lookup_by_tmdbid.assert_not_awaited()
        self.assertEqual(state, REQUEST_SERIE)
        self.verification.assert_awaited_once()
        self.assertEqual(self.subscribed(), SUBSCRIBED)

    async def test_old_option_button_while_choosing_a_serie_to_unsubscribe_from(self):
        # "0" is option 1 of an earlier search, not a serie this Gebruiker gets new episodes of
        state = await self.press("0", AFMELDEN_OPTIE)

        self.sonarr.lookup_by_tmdbid.assert_not_awaited()
        self.assertEqual(state, AFMELDEN_OPTIE)
        self.assertEqual(self.subscribed(), SUBSCRIBED)

    async def test_unsubscribe_from_a_serie(self):
        state = await self.press("1399", AFMELDEN_OPTIE)

        self.assertEqual(state, ConversationHandler.END)
        self.sonarr.lookup_by_tmdbid.assert_awaited_once_with("1399")
        self.assertEqual(self.subscribed(), {})
        [line] = self.lines("series_updates")
        self.assertEqual(line["msg"], "unsubscribed from new episodes of Game of Thrones (2011)")
        self.assertEqual((line["outcome"], line["media_title"], line["tmdb_id"]),
                         ("unsubscribed", "Game of Thrones", 1399))
        [message] = [c.args[0] for c in self.telegram.send_admin_message.await_args_list]
        self.assertIn("User has ubsubscribed to the serie Game of Thrones", message)
        self.log.logger.assert_not_awaited()

    async def test_nothing_to_unsubscribe_from(self):
        self.data_json.write_text(json.dumps({"notify_list": {}}))

        state = await self.subscribe.afmelden(*await self.message_and_context())

        self.assertEqual(state, ConversationHandler.END)
        [line] = self.lines("series_updates")
        self.assertEqual((line["msg"], line["outcome"]),
                         ("nothing to unsubscribe from", "nothing_to_unsubscribe"))

    async def test_search_for_a_serie_to_subscribe_to(self):
        # Only a serie that is downløaded and still running can be chosen
        self.sonarr.lookup_by_name = AsyncMock(return_value=[{**THE_BEAR, "ended": True}, THE_BEAR, {"title": "X"}])

        await self.subscribe.aanmeld_optie(*await self.message_and_context("the *bear*"))

        [line] = self.lines("search_term")
        self.assertEqual(line["msg"], "searched 'the *bear*' for series updates: 1 result (3 found in Sonarr)")
        self.assertEqual((line["query"], line["media_type"], line["purpose"], line["results"]),
                         ("the *bear*", "series", "series_updates", 1))

    async def message_and_context(self, text: str = "/afmelden_serie"):
        """ A message of user 1 with this text, and its context """
        update = MagicMock()
        update.message.text = text
        update.effective_user.id = 1
        context = MagicMock()
        context.user_data = {"gebruiker": "test"}
        return update, context

    async def test_serie_button_while_choosing_a_serie_to_subscribe_to(self):
        state = await self.press("serie_request", AANMELD_CHOICE, aanmeld_object=[THE_BEAR])

        self.assertEqual(state, REQUEST_SERIE)
        self.verification.assert_awaited_once()
        self.assertEqual(self.subscribed(), SUBSCRIBED)

    async def test_subscribe_to_a_serie(self):
        # Ended series get no button, so the callback_data is the index in the full Sonarr
        # result and can have two digits
        state = await self.press("10", AANMELD_CHOICE, aanmeld_object=[{"ended": True}] * 10 + [THE_BEAR])

        self.assertEqual(state, ConversationHandler.END)
        self.assertIn("136315", self.subscribed())
        [line] = self.lines("series_updates")
        self.assertEqual(line["msg"], "subscribed to new episodes of The Bear (2022)")
        self.assertEqual((line["outcome"], line["tmdb_id"]), ("subscribed", 136315))


if __name__ == "__main__":
    unittest.main()
