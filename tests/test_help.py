#!/usr/bin/python3

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.ext import ConversationHandler

from src.commands.help import Help
from src.commands.privacy import Privacy
from src.log import setup_logging
from src.states import HELP_CHOICE, HELP_OTHER
from test_conversation import message, press
from test_log import MAIN, LogFolder


class HelpTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ /help, its menu and a question, and /privacy """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))
        self.enterContext(patch("src.commands.help.asyncio.sleep", AsyncMock()))
        self.enterContext(patch("src.commands.privacy.asyncio.sleep", AsyncMock()))

        self.functions = MagicMock(send_message=AsyncMock())
        self.telegram = MagicMock(send_admin_message=AsyncMock())
        self.help = Help(self.functions, self.telegram)

    async def test_help_and_its_button_in_the_start_menu(self):
        self.assertEqual(await self.help.help_command(message("/help"), MagicMock()), HELP_CHOICE)
        self.assertEqual(await self.help.help_command_button(press("info"), MagicMock()), HELP_CHOICE)

        command, choice = self.read(MAIN)
        self.assertEqual((command["event"], command["command"]), ("command", "/help"))
        self.assertEqual((choice["event"], choice["msg"]), ("menu_choice", "chose 'information' in the start menu"))

    async def test_a_choice_in_the_help_menu(self):
        for button, choose in [("help_use", self.help.usage), ("help_faq", self.help.faq),
                               ("help_new_account", self.help.new_account), ("help_quality", self.help.quality)]:
            self.assertEqual(await choose(press(button), MagicMock()), ConversationHandler.END)
        self.assertEqual(await self.help.other(press("help_other"), MagicMock()), HELP_OTHER)

        lines = self.lines("menu_choice")
        self.assertEqual([line["msg"] for line in lines], [
            "chose 'how to use this bot' in the help menu",
            "chose 'frequently asked questions' in the help menu",
            "chose 'new account' in the help menu",
            "chose 'quality' in the help menu",
            "chose 'other' in the help menu",
        ])
        self.assertEqual({line["menu"] for line in lines}, {"help"})
        self.assertEqual({line["logger"] for line in lines}, {"commands.help"})
        self.assertEqual([line["src"].split(" in ")[1] for line in lines],
                         ["usage", "faq", "new_account", "quality", "other"])
        self.assertEqual([call.args[1] for call in self.telegram.send_admin_message.await_args_list], [
            "help: how to use this bot", "help: frequently asked questions", "help: new account", "help: quality",
            "help: other",
        ])

    async def test_how_to_use_names_the_commands_for_updates(self):
        await self.help.usage(press("help_use"), MagicMock())

        sent = [call.args for call in self.functions.send_message.await_args_list]
        for title, commands in [("4. Aan- en afmelden serie updates", ("/aanmelden_serie", "/afmelden_serie")),
                                ("5. Aan- en afmelden algemene updates", ("/aanmelden_updates", "/afmelden_updates"))]:
            with self.subTest(title=title):
                [args] = [args for args in sent if title in args[0]]
                # Not MarkdownV2: there the underscores of the commands would start italics
                self.assertEqual(args[4:], ("HTML",))
                for command in commands:
                    self.assertIn(f"<b>{command}</b>", args[0])

    async def test_a_question_is_logged_as_it_was_typed(self):
        state = await self.help.other_reply(message("Kan *Dune* in 4K?\nGroet, Piet"), MagicMock())

        self.assertEqual(state, ConversationHandler.END)
        [line] = self.read(MAIN)
        self.assertEqual((line["event"], line["msg"], line["text"]),
                         ("help_question", "asked a question: 'Kan *Dune* in 4K?\nGroet, Piet'",
                          "Kan *Dune* in 4K?\nGroet, Piet"))
        [(text, about)] = [call.args for call in self.telegram.send_admin_message.await_args_list]
        self.assertEqual(about, "question via /help")
        self.assertIn("Kan *Dune* in 4K?", text)

    async def test_privacy(self):
        await Privacy(self.functions).privacy_command(message("/privacy"), MagicMock())

        [line] = self.read(MAIN)
        self.assertEqual((line["event"], line["msg"]), ("command", "command /privacy"))


if __name__ == "__main__":
    unittest.main()
