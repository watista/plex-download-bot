#!/usr/bin/python3

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from telegram import CallbackQuery, Chat, Message, MessageEntity, Update, User
from telegram.ext import Application, ConversationHandler

from src.bot import Bot
from src.commands.subscribe import Subscribe
from src.log import setup_logging
from src.states import AFMELDEN_OPTIE, HELP_CHOICE, MOVIE_OPTION, VERIFY_PWD
from test_interaction import fake_account_for
from test_log import MAIN, LogFolder


def message(text: str, user_id: int = 1, first_name: str = "Wouter") -> Update:
    """ An update with a private message of this user; a text starting with / is a command """
    user = User(user_id, first_name, is_bot=False)
    entities = [MessageEntity(MessageEntity.BOT_COMMAND, 0, len(text.split()[0]))] if text.startswith("/") else None
    sent = Message(1, datetime.now(), Chat(user_id, Chat.PRIVATE), from_user=user, text=text, entities=entities)
    # A command like /start@plex_bot is only for the bot with that name
    sent.set_bot(MagicMock(username="plex_bot"))
    return Update(1, message=sent)


def press(data: str, user_id: int = 1, first_name: str = "Wouter") -> Update:
    """ An update with a press on the button with this callback_data, in the private chat of this user """
    user = User(user_id, first_name, is_bot=False)
    query = CallbackQuery("1", user, "1", data=data,
                          message=Message(1, datetime.now(), Chat(user_id, Chat.PRIVATE)))
    query.set_bot(MagicMock(answer_callback_query=AsyncMock()))
    return Update(1, callback_query=query)


class ConversationTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ The handlers of src/bot.py: input the bot ignores, and a Gesprek that expires """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))

        # Bot with fake handlers, except for Subscribe, so only the catch-all and the Gesprek itself write lines
        self.bot = Bot.__new__(Bot)
        for name in ("start", "help", "message", "account", "movie", "serie", "maintenance", "privacy", "function"):
            setattr(self.bot, name, MagicMock())
        self.bot.start.outside_conversation = AsyncMock()
        self.bot.mode = "normal"
        self.bot.allowed_users = [99]
        self.bot.account_for = fake_account_for
        self.bot.application = Application.builder().token("123:ABC").build()

        # Subscribe with a fake Sonarr and its own data.json, for its own line ignored
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data_json = Path(tmp.name) / "data.dev.json"
        data_json.write_text(json.dumps({"notify_list": {"1": {"serie_episode": {"1399": {}}}}}))
        functions = MagicMock(send_message=AsyncMock())
        self.bot.subscribe = Subscribe(SimpleNamespace(env="dev"), MagicMock(), functions, MagicMock())
        self.bot.subscribe.data_json = str(data_json)
        self.bot.subscribe.sonarr = MagicMock(lookup_by_tmdbid=AsyncMock())

        self.bot._register_handlers()
        self.conversation = self.bot.conversation

    async def send(self, update: Update, state: int | None = None):
        """ Handles the update like PTB: the first handler that takes it, while the Gesprek is in this state """
        if state is not None:
            self.conversation._conversations[(update.effective_chat.id, update.effective_user.id)] = state
        for handler in self.bot.application.handlers[0]:
            check = handler.check_update(update)
            if check:
                # The ConversationHandler hands it to one of its own handlers
                callback = check[2].callback if handler is self.conversation else handler.callback
                return await callback(update, MagicMock(user_data={"gebruiker": "wouter"}))
        self.fail("no handler took the update")

    async def test_a_button_of_an_old_message_is_ignored_with_its_value(self):
        # Option 3 of an earlier search, while the bot waits for a choice in the help menu
        await self.send(press("2"), state=HELP_CHOICE)

        [line] = self.lines("ignored")
        self.assertEqual(line["msg"], "ignored button '2' at step help_choice")
        self.assertEqual((line["input"], line["step"], line["button"]), ("button", "help_choice", "2"))

    async def test_a_button_of_an_old_message_outside_a_conversation(self):
        await self.send(press("film_notify_yes"))

        [line] = self.lines("ignored")
        self.assertEqual(line["msg"], "ignored button 'film_notify_yes' outside a conversation")
        self.assertNotIn("step", line)

    async def test_text_while_the_bot_waits_for_a_button_is_ignored_without_the_text(self):
        await self.send(message("dune part two"), state=MOVIE_OPTION)

        [line] = self.lines("ignored")
        self.assertEqual(line["msg"], "ignored text at step movie_option")
        self.assertEqual((line["input"], line["step"]), ("text", "movie_option"))
        self.assertNotIn("dune", json.dumps(line))

    async def test_an_unknown_command_is_ignored_with_the_command_but_not_its_arguments(self):
        await self.send(message("/foo@plex_bot secret words"))

        [line] = self.lines("ignored")
        self.assertEqual(line["msg"], "ignored command /foo outside a conversation")
        self.assertEqual((line["input"], line["command"]), ("command", "/foo"))
        self.assertNotIn("secret", json.dumps(line))

    async def test_a_command_in_the_middle_of_a_conversation_is_ignored(self):
        await self.send(message("/start"), state=VERIFY_PWD)

        [line] = self.lines("ignored")
        self.assertEqual(line["msg"], "ignored command /start at step verify_pwd")

    async def test_an_admin_command_of_someone_else_is_ignored(self):
        await self.send(message("/message_all"))

        [line] = self.lines("ignored")
        self.assertEqual(line["command"], "/message_all")

    async def test_a_message_without_text_is_ignored(self):
        user = User(1, "Wouter", is_bot=False)
        update = Update(1, message=Message(1, datetime.now(), Chat(1, Chat.PRIVATE), from_user=user,
                                           sticker=MagicMock()))

        await self.send(update, state=MOVIE_OPTION)

        [line] = self.lines("ignored")
        self.assertEqual(line["msg"], "ignored a message without text at step movie_option")
        self.assertEqual(line["input"], "other")

    async def test_stop_ends_the_conversation_with_a_line(self):
        self.bot.function = MagicMock(send_message=AsyncMock())

        state = await self.send(message("/stop"), state=MOVIE_OPTION)

        self.assertEqual(state, ConversationHandler.END)
        [line] = self.read(MAIN)
        self.assertEqual((line["event"], line["msg"], line["command"]), ("command", "command /stop", "/stop"))

    async def test_stop_outside_a_conversation_is_ignored(self):
        await self.send(message("/stop"))

        [line] = self.lines("ignored")
        self.assertEqual(line["msg"], "ignored command /stop outside a conversation")

    async def test_text_outside_a_conversation_is_not_ignored(self):
        await self.send(message("hunter2"))

        self.bot.start.outside_conversation.assert_awaited_once()
        self.assertEqual(self.lines("ignored"), [])

    async def test_an_old_option_button_while_choosing_a_serie_to_unsubscribe_from(self):
        # Subscribe catches this one itself, so the catch-all never sees it
        await self.send(press("0"), state=AFMELDEN_OPTIE)

        [line] = self.lines("ignored")
        self.assertEqual(line["msg"], "ignored button '0' at step afmelden_optie")
        self.assertEqual((line["input"], line["step"], line["button"]), ("button", "afmelden_optie", "0"))
        self.assertEqual(line["logger"], "commands.subscribe")

    async def expire(self, update: Update, state: int):
        """ Lets the Gesprek of the sender of this update, its last update, expire in this state """
        self.conversation._conversations[(update.effective_chat.id, update.effective_user.id)] = state
        for handler in self.conversation.states[ConversationHandler.TIMEOUT]:
            if handler.check_update(update):
                await handler.callback(update, MagicMock())

    async def test_an_expired_conversation_of_a_gebruiker(self):
        await self.expire(press("0", user_id=123456789), MOVIE_OPTION)

        [line] = self.lines("conversation_expired")
        self.assertEqual(line["msg"], "conversation expired at step movie_option")
        self.assertEqual((line["level"], line["user_id"], line["account"], line["step"]),
                         ("INFO", 123456789, "wouter", "movie_option"))
        self.assertNotIn("tg_name", line)

    async def test_an_expired_conversation_of_a_bezoeker_never_has_the_password(self):
        await self.expire(message("hunter2", user_id=777, first_name="Sanne"), VERIFY_PWD)

        [line] = self.lines("conversation_expired")
        self.assertEqual((line["user_id"], line["tg_name"], line["step"]), (777, "Sanne", "verify_pwd"))
        self.assertNotIn("account", line)
        self.assertNotIn("hunter2", self.raw(MAIN))


if __name__ == "__main__":
    unittest.main()
