#!/usr/bin/python3

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram import Chat, Message, MessageEntity, Update, User
from telegram.error import BadRequest

from src.commands.log import LogCommand
from src.log import setup_logging
from src.telegram_out import plain_text
from test_conversation import message, press
import test_search
from test_log import LogFolder


# The Beheerder, in CHAT_ID_ADMIN
ADMIN = 99

# The user list of data.json: wouter is an account of two persons
USERS = {"1": "wouter, Wouter", "3": "wouter, Sanne", "2": "anna, Anna", "5": "sander, Sander"}


def line(ts: str, msg: str, **fields) -> dict:
    """ A line of the bot in December 2026, in Dutch local time """
    return {"ts": f"2026-12-{ts}+01:00", "level": "INFO", **fields, "msg": msg, "logger": "commands.media",
            "src": "src/commands/media.py:60 in search"}


def library_line(ts: str, msg: str, **fields) -> dict:
    """ A line of a library in December 2026, with the context of the Interaction it was written in """
    return {**test_search.library_line(ts, msg, **fields), "ts": f"2026-12-{ts}+01:00"}


def in_group(text: str, user_id: int = ADMIN) -> Update:
    """ A command of this user in a group """
    user = User(user_id, "Wouter", is_bot=False)
    sent = Message(1, datetime.now(), Chat(-100, Chat.GROUP), from_user=user, text=text,
                   entities=[MessageEntity(MessageEntity.BOT_COMMAND, 0, len(text.split()[0]))])
    sent.set_bot(AsyncMock(username="plex_bot"))
    return Update(1, message=sent)


class LogCommandTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ /log: recognizing the argument, the page in HTML, the texts when nothing is found, and browsing """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-12-08T10:00:00+01:00"))

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data_json = Path(tmp.name) / "data.dev.json"
        data_json.write_text(json.dumps({"user_id": USERS, "blocked_users": {}}))

        self.command = LogCommand("dev", str(self.folder), str(data_json), "thuisserver", [ADMIN])

        # Every message that is sent or edited, with its keywords
        self.shown = []

        async def show(**kwargs) -> None:
            self.shown.append(kwargs)

        self.bot = SimpleNamespace(send_message=AsyncMock(side_effect=show), edit_message_text=AsyncMock(side_effect=show))

    def write(self, day: str, *lines: dict) -> None:
        """ Adds lines to the main file of dev of this day in December """
        with (self.folder / f"dev-plex-download-bot-2026-12-{day}.jsonl").open("a", encoding="utf-8") as file:
            for item in lines:
                file.write(json.dumps(item, ensure_ascii=False) + "\n")

    async def log(self, argument: str = "") -> str:
        """ The text of the answer to /log with this argument """
        await self.command.log_command(message(f"/log {argument}".strip(), user_id=ADMIN), SimpleNamespace(bot=self.bot))
        return self.shown[-1]["text"]

    def buttons(self) -> dict[str, str]:
        """ The buttons under the last message that was sent or edited, by their text """
        markup = self.shown[-1]["reply_markup"]
        return {button.text: button.callback_data for row in (markup.inline_keyboard if markup else ())
                for button in row}

    async def press(self, data: str) -> str:
        """ The text that the message gets after a press on a button with this callback_data """
        await self.command.page_button(press(data, user_id=ADMIN), SimpleNamespace(bot=self.bot))
        return self.shown[-1]["text"]

    def wouter(self) -> None:
        """ A day and a half of wouter, with a Bug and its admin message """
        self.write("07",
                   line("07T14:05:01.000", "command /start", user_id=1, account="wouter", event="command"),
                   line("07T14:05:30.000", "command /start", user_id=2, account="anna", event="command"),
                   line("07T14:06:02.000", "searched 'dune' for movie: 7 results", user_id=1, account="wouter",
                        event="search_term", interaction_id="h3m8tq"),
                   {**line("07T14:06:10.000", "Radarr refused the movie request: This movie has already been added",
                           user_id=1, account="wouter", reason="This movie has already been added", http_status=400,
                           fault="bug", service="radarr", interaction_id="k7p2qx", exc_type="HTTPStatusError",
                           exc="Traceback (most recent call last):\n  ..."), "level": "ERROR"},
                   library_line("07T14:06:10.500", "Retrying after the error", user_id=1, account="wouter",
                                interaction_id="k7p2qx"),
                   line("07T14:06:11.000", "admin message sent: bug", user_id=1, account="wouter",
                        event="admin_message_sent", fault="bug", service="radarr", interaction_id="k7p2qx"))
        self.write("08",
                   line("08T09:12:00.000", "sent user message online about Dune (2021)", user_id=1, account="wouter",
                        event="user_message", kind="online", interaction_id="m3tq8w", job="check_notify_list"))

    async def test_the_lines_of_a_person_per_day_with_the_oldest_on_top(self):
        self.wouter()

        self.assertEqual(await self.log("wouter"), "\n".join([
            "📋 <b>wouter</b>",
            "",
            "Mon 7 Dec",
            "<b>14:05</b> command /start",
            "<b>14:06</b> searched 'dune' for movie: 7 results",
            "⚠️ <b>14:06</b> Bug · radarr: This movie has already been added <code>k7p2qx</code>",
            "<b>14:06</b> admin message sent: bug",
            "Tue 8 Dec",
            "<b>09:12</b> sent user message online about Dune (2021)",
            "",
            "Logs on thuisserver since 2026-12-07",
        ]))
        self.assertEqual(self.bot.send_message.await_args.kwargs["parse_mode"], "HTML")
        self.assertEqual(self.buttons(), {})

    async def test_the_lines_of_one_interaction_by_its_code(self):
        self.wouter()

        self.assertEqual(await self.log("k7p2qx"), "\n".join([
            "📋 Code <code>k7p2qx</code> · wouter",
            "",
            "Mon 7 Dec",
            "⚠️ <b>14:06</b> Bug · radarr: This movie has already been added (HTTPStatusError) <code>k7p2qx</code>",
            "<b>14:06</b> Retrying after the error",
            "<b>14:06</b> admin message sent: bug",
            "",
            "Traceback over SSH: <code>grep k7p2qx</code>",
            "Logs on thuisserver since 2026-12-07",
        ]))

    async def test_the_header_of_a_code_names_the_job(self):
        self.wouter()

        self.assertTrue((await self.log("m3tq8w")).startswith("📋 Code <code>m3tq8w</code> · check_notify_list\n"))

    async def test_a_bezoeker_by_user_id_with_the_telegram_name(self):
        self.write("07", line("07T08:00:00.000", "login: wrong password (attempt 1 of 3)", user_id=777,
                              tg_name="Piet", event="login"))

        self.assertTrue((await self.log("777")).startswith("📋 <b>777 (Piet)</b>\n"))

    async def test_a_shared_account_names_each_line_and_says_who_is_who(self):
        self.write("07",
                   line("07T08:00:00.000", "login: ok", user_id=3, tg_name="Sanne", event="login"),
                   line("07T08:01:00.000", "command /start", user_id=3, account="wouter", event="command"),
                   line("07T08:02:00.000", "command /help", user_id=1, account="wouter", event="command"))

        self.assertEqual(await self.log("Wouter"), "\n".join([
            "📋 <b>wouter</b>",
            "Wouter: <code>1</code> · Sanne: <code>3</code>",
            "",
            "Mon 7 Dec",
            "<b>08:00</b> Sanne: login: ok",
            "<b>08:01</b> Sanne: command /start",
            "<b>08:02</b> Wouter: command /help",
            "",
            "Logs on thuisserver since 2026-12-07",
        ]))

    async def test_one_person_of_a_shared_account_by_user_id_gets_no_names(self):
        self.write("07",
                   line("07T08:01:00.000", "command /start", user_id=3, account="wouter", event="command"),
                   line("07T08:02:00.000", "command /help", user_id=1, account="wouter", event="command"))

        self.assertIn("<b>08:01</b> command /start", await self.log("3"))

    async def test_a_line_over_200_characters_is_cut(self):
        self.write("07", line("07T08:00:00.000", "x" * 300, user_id=1, account="wouter"))

        [shown] = [row for row in (await self.log("wouter")).split("\n") if row.startswith("<b>08:00</b>")]
        self.assertEqual(shown, f"<b>08:00</b> {'x' * 199}…")

    async def test_msg_is_escaped_for_html(self):
        self.write("07", line("07T08:00:00.000", "searched '<b>Tom & Jerry</b>'", user_id=1, account="wouter"))

        self.assertIn("<b>08:00</b> searched '&lt;b&gt;Tom &amp; Jerry&lt;/b&gt;'", await self.log("wouter"))

    async def test_recognized_as_digits_then_account_name_then_code(self):
        self.write("07",
                   line("07T08:00:00.000", "command /start of sander", user_id=5, account="sander"),
                   # A Code that is also the name of an account
                   line("07T08:01:00.000", "command /start of anna", user_id=2, account="anna", interaction_id="sander"),
                   line("07T08:02:00.000", "command /help of 234567", user_id=234567, tg_name="Kees"),
                   line("07T08:03:00.000", "command /help in k7p2qx", user_id=2, account="anna", interaction_id="k7p2qx"),
                   # An account that is no longer in the user list
                   line("07T08:04:00.000", "command /stop of piet", user_id=8, account="Piet"))

        cases = {
            "5": "command /start of sander",
            "SANDER": "command /start of sander",
            "sander": "command /start of sander",
            # Only digits, though it has the form of a Code
            "234567": "command /help of 234567",
            "K7P2QX": "command /help in k7p2qx",
            "piet": "command /stop of piet",
        }
        for argument, shown in cases.items():
            with self.subTest(argument=argument):
                text = await self.log(argument)
                self.assertIn(shown, text)
                self.assertEqual(text.count("<b>08:0"), 1)

    async def test_the_texts_when_nothing_is_found(self):
        self.wouter()

        self.assertEqual(await self.log("Sander"), "No log lines for sander on thuisserver since 2026-12-07")
        self.assertEqual(await self.log("42"), "No log lines for 42 on thuisserver since 2026-12-07")
        self.assertEqual(await self.log("k7p2qz"), "Code k7p2qz not found on thuisserver")
        self.assertEqual(await self.log("nobody"), "Unknown user or code: nobody")
        self.assertEqual(await self.log("<b>"), "Unknown user or code: &lt;b&gt;")

    async def test_without_an_argument_a_short_explanation(self):
        text = await self.log()

        self.assertIn("/log &lt;account name | user ID | code&gt;", text)

    async def test_the_line_admin_command_with_the_argument(self):
        await self.log()
        await self.log("wouter")

        self.assertEqual([(line["msg"], line.get("argument")) for line in self.read_admin_commands()],
                         [("admin command /log", None), ("/log wouter", "wouter")])
        self.assertEqual({line["command"] for line in self.read_admin_commands()}, {"/log"})

    def read_admin_commands(self) -> list[dict]:
        return [line for line in self.read("dev-plex-download-bot-2026-12-08.jsonl")
                if line.get("event") == "admin_command"]

    async def test_one_page_at_a_time_and_browsing_back_and_forth(self):
        # Three hours of searches on two days, about three pages
        searches = {day: [f"searched 'title {day} {hour}:{minute:02}' for movie: 3 results"
                          for hour in range(8, 11) for minute in range(0, 60, 2)] for day in ("07", "08")}
        for day, msgs in searches.items():
            self.write(day, *[line(f"{day}T{index // 30 + 8:02}:{index % 30 * 2:02}:00.000", msg, user_id=1,
                                   account="wouter", event="search_term") for index, msg in enumerate(msgs)])
        everything = searches["07"] + searches["08"]

        # As many as fit in one message, as Telegram counts: without the tags, in UTF-16
        first = await self.log("wouter")
        self.assertLessEqual(self.length(first), 4096)
        self.assertGreater(self.length(first), 4096 - 60)
        self.assertIn("searched 'title 08 10:58'", first)
        self.assertEqual(list(self.buttons()), ["⬅️ Earlier"])

        # Earlier: the lines right before the first page, which go on over the file of the day before
        earlier = await self.press(self.buttons()["⬅️ Earlier"])
        self.assertLessEqual(self.length(earlier), 4096)
        self.assertEqual(list(self.buttons()), ["⬅️ Earlier", "Later ➡️"])
        oldest_on_first = first.split("\n")[3].split("</b> ", 1)[1]
        newest_on_earlier = earlier.split("\n")[-3].split("</b> ", 1)[1]
        self.assertEqual(everything.index(newest_on_earlier) + 1, everything.index(oldest_on_first))

        # Back to the start, and Later again up to the first page
        while "⬅️ Earlier" in self.buttons():
            await self.press(self.buttons()["⬅️ Earlier"])
        self.assertIn("searched 'title 07 8:00'", self.shown[-1]["text"])
        while "Later ➡️" in self.buttons():
            await self.press(self.buttons()["Later ➡️"])
        self.assertEqual(self.shown[-1]["text"], first)
        self.assertEqual(list(self.buttons()), ["⬅️ Earlier"])

        # Each press is an admin command of its own
        self.assertEqual({line.get("button") for line in self.read_admin_commands()}, {None, "earlier", "later"})

    @staticmethod
    def length(page: str) -> int:
        """ The length of a page as Telegram counts it """
        return len(plain_text(page, "HTML").encode("utf-16-le")) // 2

    async def test_the_position_and_the_argument_fit_in_the_callback_data(self):
        self.write("07", *[line(f"07T08:{minute:02}:00.000", "y" * 150, user_id=1, account="wouter")
                           for minute in range(60)])

        await self.log("wouter")

        [data] = self.buttons().values()
        self.assertLessEqual(len(data.encode()), 64)
        self.assertTrue(data.startswith("log:"))

    async def test_formatting_that_telegram_rejects_goes_again_as_plain_text(self):
        self.wouter()
        self.bot.send_message.side_effect = [BadRequest("Can't parse entities: unsupported start tag"), None]

        await self.command.log_command(message("/log wouter", user_id=ADMIN), SimpleNamespace(bot=self.bot))

        retry = self.bot.send_message.await_args.kwargs
        self.assertIsNone(retry["parse_mode"])
        self.assertTrue(retry["text"].startswith("⚠️ Telegram rejected the formatting: Can't parse entities"))
        self.assertIn("14:06 Bug · radarr: This movie has already been added k7p2qx", retry["text"])
        [bug] = [line for line in self.read("dev-plex-download-bot-2026-12-08.jsonl") if line.get("fault")]
        self.assertEqual((bug["level"], bug["fault"], bug["service"]), ("ERROR", "bug", "telegram"))

    async def test_a_page_that_did_not_change_is_left_as_it_is(self):
        self.wouter()
        self.bot.edit_message_text.side_effect = BadRequest("Message is not modified: specified new message content "
                                                            "and reply markup are exactly the same")

        await self.command.page_button(press("log:l:p:20261207:0:wouter", user_id=ADMIN), SimpleNamespace(bot=self.bot))

        self.bot.edit_message_text.assert_awaited_once()
        self.bot.send_message.assert_not_awaited()


class WhoTest(unittest.TestCase):
    """ /log and its buttons are only for the Beheerder, and only in the private chat """

    def setUp(self):
        self.command, self.buttons = LogCommand("dev", "log", "data.dev.json", "thuisserver", [ADMIN]).handlers()

    def test_the_beheerder_in_the_private_chat(self):
        self.assertTrue(self.command.check_update(message("/log wouter", user_id=ADMIN)))
        self.assertTrue(self.buttons.check_update(press("log:e:p:20261207:0:wouter", user_id=ADMIN)))

    def test_someone_else(self):
        self.assertFalse(self.command.check_update(message("/log wouter", user_id=1)))
        self.assertFalse(self.buttons.check_update(press("log:e:p:20261207:0:wouter", user_id=1)))

    def test_the_beheerder_in_a_group(self):
        self.assertFalse(self.command.check_update(in_group("/log wouter")))

    def test_only_the_buttons_of_log(self):
        self.assertFalse(self.buttons.check_update(press("movie_request", user_id=ADMIN)))


if __name__ == "__main__":
    unittest.main()
