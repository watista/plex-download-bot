#!/usr/bin/python3

import asyncio
import unittest
from types import SimpleNamespace

from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from src.faults import Fault, FaultKind
from src.interaction import guard_job
from src.log import setup_logging
from src.telegram_out import Delivery, TelegramOut
from test_interaction import FakeFaults
from test_log import MAIN, SECRETS, LogFolder


ADMIN_CHAT = "-1001234"

# The user list of data.json: user ID to account name
ACCOUNTS = {555: "anna"}


async def fake_account_for(user_id: int) -> str | None:
    """ account_for on a fake user list """
    return ACCOUNTS.get(user_id)


class FakeBot:
    """ The PTB bot as far as the verzendfunctie uses it: records every attempt, and answers like Telegram would.

    answers holds per attempt the exception Telegram answers with, or None when it delivers the message.
    """

    def __init__(self, *answers: Exception | None):
        self.attempts = []
        self._answers = list(answers)

    async def send_message(self, chat_id, text, parse_mode=None, disable_notification=None, **kwargs):
        self.attempts.append(SimpleNamespace(chat_id=chat_id, text=text, parse_mode=parse_mode,
                                             silent=disable_notification))
        answer = self._answers.pop(0) if self._answers else None
        if answer is not None:
            raise answer


class SendTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ send: the one way a message of the bot itself goes to Telegram """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))

    def telegram(self, *answers: Exception | None) -> TelegramOut:
        self.bot = FakeBot(*answers)
        return TelegramOut(self.bot, ADMIN_CHAT, fake_account_for)

    async def test_secrets_are_masked(self):
        telegram = self.telegram()

        await telegram.send(555, f"token {SECRETS['BOT_TOKEN']} and key {SECRETS['RADARR_API']}", "HTML")

        [attempt] = self.bot.attempts
        self.assertEqual(attempt.text, "token *** and key ***")
        self.assertEqual((attempt.chat_id, attempt.parse_mode, attempt.silent), (555, "HTML", False))

    async def test_a_message_is_cut_at_4096_characters(self):
        telegram = self.telegram()

        await telegram.send(555, "a" * 4096, None)
        await telegram.send(555, "b" * 4097, None)

        self.assertEqual([len(attempt.text) for attempt in self.bot.attempts], [4096, 4096])
        self.assertEqual(self.bot.attempts[1].text, "b" * 4096)

    async def test_rejected_html_goes_again_as_plain_text_with_a_bug_line(self):
        rejection = "Can't parse entities: unsupported start tag \"x\" at byte offset 0"
        telegram = self.telegram(BadRequest(rejection), None)

        delivery = await telegram.send(ADMIN_CHAT, "🐞 <b>Bug</b> · Radarr &amp; Sonarr <x>", "HTML", silent=True)

        self.assertTrue(delivery.delivered)
        html, plain = self.bot.attempts
        self.assertEqual(html.parse_mode, "HTML")
        self.assertEqual(plain.text, f"⚠️ Telegram rejected the formatting: {rejection}\n\n🐞 Bug · Radarr & Sonarr ")
        self.assertEqual((plain.chat_id, plain.parse_mode, plain.silent), (ADMIN_CHAT, None, True))
        [line] = self.read(MAIN)
        self.assertEqual((line["level"], line["fault"], line["service"]), ("ERROR", "bug", "telegram"))
        self.assertEqual((line["reason"], line["exc_type"]), (rejection, "BadRequest"))
        self.assertIn("exc", line)

    async def test_rejected_markdown_goes_again_without_its_escapes(self):
        telegram = self.telegram(BadRequest("Can't parse entities: character '!' is reserved"), None)

        await telegram.send(ADMIN_CHAT, "✅ *Bot gestart* \\(live\\) om 03\\-11\\-2026!", "MarkdownV2")

        self.assertEqual(self.bot.attempts[1].text.split("\n\n", 1)[1], "✅ *Bot gestart* (live) om 03-11-2026!")

    async def test_when_telegram_also_rejects_the_plain_text_it_stays_with_the_line(self):
        telegram = self.telegram(BadRequest("Can't parse entities: can't find end tag"), BadRequest("Message is too long"))

        delivery = await telegram.send(555, "<b>Goed nieuws", "HTML")

        self.assertFalse(delivery.delivered)
        self.assertEqual(delivery.reason, "Message is too long")
        self.assertEqual(len(self.bot.attempts), 2)
        [line] = self.read(MAIN)
        self.assertEqual((line["level"], line["fault"]), ("ERROR", "bug"))

    async def test_telegram_not_responding_is_a_disruption(self):
        for error in NetworkError("httpx.ConnectError: [Errno -3] Try again"), TimedOut(), RetryAfter(30):
            with self.subTest(error=type(error).__name__):
                telegram = self.telegram(error)

                with self.assertRaises(Fault) as caught:
                    await telegram.send(555, "Goed nieuws", None)

                fault = caught.exception
                self.assertEqual((fault.kind, fault.service), (FaultKind.DISRUPTION, "telegram"))
                self.assertEqual((fault.what, fault.reason), ("Telegram is not responding", str(error)))
                self.assertIs(fault.__cause__, error)

        # The wrapper writes the line of a Fault, not send
        self.assertEqual(self.read(MAIN), [])

    async def test_forbidden_gives_not_delivered_with_the_reason(self):
        telegram = self.telegram(Forbidden("Forbidden: bot was blocked by the user"))

        delivery = await telegram.send(555, "Goed nieuws", None)

        self.assertFalse(delivery.delivered)
        self.assertEqual(delivery.reason, "Forbidden: bot was blocked by the user")
        self.assertEqual(self.read(MAIN), [])

    async def test_another_bad_request_falls_through_without_a_second_attempt(self):
        telegram = self.telegram(BadRequest("Chat not found"))

        with self.assertRaises(BadRequest):
            await telegram.send(555, "<b>Goed nieuws</b>", "HTML")

        self.assertEqual(len(self.bot.attempts), 1)


class SendAdminMessageTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ send_admin_message: the other messages to the Beheerder, which keep their content and MarkdownV2 """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:30:00+01:00"))

    async def test_an_admin_message_is_escaped_for_markdown_except_its_bold(self):
        bot = FakeBot()

        delivery = await TelegramOut(bot, ADMIN_CHAT, fake_account_for).send_admin_message(
            "*ℹ️ User notified: The film Dune (438631) is online ℹ️*\nUser ID: 555\nGebruiker: anna_b", "user notified")

        self.assertTrue(delivery.delivered)
        [attempt] = bot.attempts
        self.assertEqual((attempt.chat_id, attempt.parse_mode, attempt.silent), (ADMIN_CHAT, "MarkdownV2", False))
        self.assertEqual(attempt.text,
                         "*ℹ️ User notified: The film Dune \\(438631\\) is online ℹ️*\nUser ID: 555\nGebruiker: anna\\_b")

    async def test_an_admin_message_writes_what_it_was_about_but_not_its_text(self):
        await TelegramOut(FakeBot(), ADMIN_CHAT, fake_account_for).send_admin_message(
            "✅ Bot gestart (live) om 03-11-2026 14:30:00.", "bot started")

        [line] = self.read(MAIN)
        self.assertEqual((line["level"], line["event"]), ("INFO", "admin_message_sent"))
        self.assertIn("bot started", line["msg"])
        self.assertNotIn("fault", line)
        self.assertNotIn("gestart", self.raw(MAIN))

    async def test_an_admin_message_that_does_not_arrive_is_a_warning(self):
        bot = FakeBot(Forbidden("Forbidden: bot was kicked from the group chat"))

        delivery = await TelegramOut(bot, ADMIN_CHAT, fake_account_for).send_admin_message("✅ Bot gestart", "bot started")

        self.assertFalse(delivery.delivered)
        [line] = self.read(MAIN)
        self.assertEqual((line["level"], line["reason"]), ("WARNING", "Forbidden: bot was kicked from the group chat"))
        self.assertNotIn("event", line)


class SendUserMessageTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ send_user_message: every Gebruikersbericht with a line user_message about its receiver """

    DUNE = {"title": "Dune", "year": 2021, "tmdbId": 438631, "path": "/films/Dune (2021)"}

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:30:00+01:00"))

    async def in_a_run(self, telegram: TelegramOut, user_id, kind: str, text: str, media=None) -> Delivery:
        """ send_user_message in a run of check_notify_list, a job without user fields of its own """
        sent = guard_job(lambda context: telegram.send_user_message(user_id, kind, text, media), FakeFaults())
        return await asyncio.create_task(sent(SimpleNamespace(job=SimpleNamespace(name="check_notify_list"))))

    async def test_a_user_message_gets_a_line_with_its_receiver_and_the_media(self):
        bot = FakeBot()

        # A user ID as data.json has it
        delivery = await self.in_a_run(TelegramOut(bot, ADMIN_CHAT, fake_account_for), "555", "online",
                                       "Goed nieuws! 🎉 <b>Dune</b> staat nu online op Plęx.", self.DUNE)

        self.assertTrue(delivery.delivered)
        [attempt] = bot.attempts
        self.assertEqual((attempt.chat_id, attempt.parse_mode), (555, "HTML"))
        [line] = self.read(MAIN)
        self.assertEqual(list(line), ["ts", "level", "user_id", "account", "event", "msg", "kind", "media_title",
                                      "media_year", "tmdb_id", "interaction_id", "job", "logger", "src"])
        self.assertEqual((line["level"], line["user_id"], line["account"]), ("INFO", 555, "anna"))
        self.assertEqual((line["event"], line["kind"], line["job"]), ("user_message", "online", "check_notify_list"))
        self.assertEqual((line["media_title"], line["media_year"], line["tmdb_id"]), ("Dune", 2021, 438631))

    async def test_a_user_message_that_does_not_arrive_is_a_warning_with_the_reason(self):
        bot = FakeBot(Forbidden("Forbidden: bot was blocked by the user"))

        delivery = await self.in_a_run(TelegramOut(bot, ADMIN_CHAT, fake_account_for), 555, "broadcast",
                                       "Plex is vanavond even offline")

        self.assertFalse(delivery.delivered)
        [line] = self.read(MAIN)
        self.assertEqual((line["level"], line["event"], line["kind"]), ("WARNING", "user_message", "broadcast"))
        self.assertEqual((line["user_id"], line["account"]), (555, "anna"))
        self.assertEqual(line["reason"], "Forbidden: bot was blocked by the user")
        self.assertNotIn("fault", line)
        # The text of a broadcast is in the line admin_command of the Beheerder already
        self.assertNotIn("offline", self.raw(MAIN))

    async def test_a_receiver_outside_the_user_list_has_no_account(self):
        await self.in_a_run(TelegramOut(FakeBot(), ADMIN_CHAT, fake_account_for), 777, "message", "Hoi")

        [line] = self.read(MAIN)
        self.assertEqual(line["user_id"], 777)
        self.assertFalse({"account", "tg_name"} & line.keys())


if __name__ == "__main__":
    unittest.main()
