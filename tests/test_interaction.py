#!/usr/bin/python3

import asyncio
import json
import logging
import tempfile
import unittest
import warnings
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from telegram import Chat, Message, Update, User
from telegram.ext import Application, CallbackContext
from telegram.warnings import PTBUserWarning

from src.bot import Bot
from src.interaction import InteractionProcessor, account_for, current_code, guard_job, new_code
from src.log import get_logger, setup_logging
from test_log import MAIN, LogFolder


CODE = r"^[23456789abcdefghjkmnpqrstuvwxyz]{6}$"

# The user list of data.json: user ID to account name
ACCOUNTS = {123456789: "wouter", 555: "anna"}


async def fake_account_for(user_id: int) -> str | None:
    """ account_for on a fake user list """
    return ACCOUNTS.get(user_id)


def message_from(user_id: int, first_name: str, text: str = "/start") -> Update:
    """ An update with a private message of this Telegram user """
    user = User(user_id, first_name, is_bot=False)
    return Update(1, message=Message(1, datetime.now(), Chat(user_id, Chat.PRIVATE), from_user=user, text=text))


class UpdateTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ Every update is an Interaction, through the processor that PTB hands each update """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))
        self.processor = InteractionProcessor(1, fake_account_for)

    async def handle(self) -> str | None:
        """ A handler that writes a line of its own and one of a library, and returns the Code it saw """
        get_logger("src.commands.start").info("command /start", event="command")
        logging.getLogger("telegram.ext.Application").warning("a line of a library")
        return current_code()

    async def test_every_line_of_an_update_of_a_gebruiker_gets_the_code_user_id_and_account(self):
        codes = []

        async def handle():
            codes.append(await self.handle())

        await self.processor.process_update(message_from(123456789, "Wouter"), handle())

        [code] = codes
        self.assertRegex(code, CODE)
        own, library = self.read(MAIN)
        for line in own, library:
            self.assertEqual(line["user_id"], 123456789)
            self.assertEqual(line["account"], "wouter")
            self.assertNotIn("tg_name", line)
            self.assertEqual(line["interaction_id"], code)
        self.assertEqual(library["logger"], "telegram.ext.Application")
        self.assertNotIn("event", library)

    async def test_a_bezoeker_gets_the_telegram_name_and_no_account(self):
        await self.processor.process_update(message_from(777, "Wouter"), self.handle())

        own, library = self.read(MAIN)
        for line in own, library:
            self.assertEqual(line["user_id"], 777)
            self.assertEqual(line["tg_name"], "Wouter")
            self.assertNotIn("account", line)
            self.assertRegex(line["interaction_id"], CODE)

    async def test_the_context_is_reset_after_every_update(self):
        await self.processor.process_update(message_from(123456789, "Wouter"), self.handle())
        get_logger("src.bot").info("polling")
        await self.processor.process_update(message_from(777, "Sanne"), self.handle())

        first, _, between, second, _ = self.read(MAIN)
        self.assertEqual(list(between), ["ts", "level", "msg", "logger", "src"])
        self.assertNotEqual(second["interaction_id"], first["interaction_id"])
        self.assertEqual(second["tg_name"], "Sanne")
        self.assertNotIn("account", second)
        self.assertIsNone(current_code())

    async def test_the_context_is_also_reset_after_an_exception(self):
        async def handle():
            await self.handle()
            raise RuntimeError("handler failed")

        with self.assertRaises(RuntimeError):
            await self.processor.process_update(message_from(123456789, "Wouter"), handle())
        get_logger("src.bot").info("polling")

        *_, after = self.read(MAIN)
        self.assertEqual(list(after), ["ts", "level", "msg", "logger", "src"])

    async def test_an_update_is_still_handled_when_the_user_list_cannot_be_read(self):
        async def unreadable(user_id: int) -> str | None:
            raise FileNotFoundError("data.dev.json")

        processor = InteractionProcessor(1, unreadable)
        await processor.process_update(message_from(123456789, "Wouter"), self.handle())

        error, own, library = self.read(MAIN)
        self.assertEqual((error["level"], error["exc_type"]), ("ERROR", "FileNotFoundError"))
        self.assertEqual(error["msg"], "could not look up the account of user 123456789")
        self.assertEqual(own["event"], "command")
        for line in error, own, library:
            self.assertEqual(line["user_id"], 123456789)
            self.assertFalse({"account", "tg_name"} & line.keys())
            self.assertEqual(line["interaction_id"], error["interaction_id"])

    async def test_a_person_given_as_keywords_replaces_the_person_of_the_update(self):
        async def handle():
            get_logger("src.telegram_out").info("user message: online", user_id=555, account="anna")

        await self.processor.process_update(message_from(777, "Sanne"), handle())

        [line] = self.read(MAIN)
        self.assertEqual(line["user_id"], 555)
        self.assertEqual(line["account"], "anna")
        self.assertNotIn("tg_name", line)
        self.assertRegex(line["interaction_id"], CODE)

    async def test_an_update_without_a_user_only_gets_a_code(self):
        update = Update(2, channel_post=Message(1, datetime.now(), Chat(-100, Chat.CHANNEL), text="news"))

        await self.processor.process_update(update, self.handle())

        own, library = self.read(MAIN)
        for line in own, library:
            self.assertRegex(line["interaction_id"], CODE)
            self.assertFalse({"user_id", "account", "tg_name", "job"} & line.keys())


class JobTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ Every run of a job is an Interaction of its own, run the way PTB runs a job """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:30:00+01:00"))
        self.application = Application.builder().token("123:ABC").build()

    async def run_job(self, callback, name: str) -> None:
        """ One run of a job, registered the way src/bot.py does it; the scheduler itself does not run """
        job = self.application.job_queue.run_once(guard_job(callback), when=3600, name=name)
        await job.run(self.application)

    @staticmethod
    async def check(context: CallbackContext) -> None:
        """ A job that writes a line of its own and one of a library """
        get_logger("src.commands.schedule").info("checked 14 items")
        logging.getLogger("apscheduler.scheduler").warning("a line of a library")

    async def test_a_job_gets_a_context_of_its_own_not_that_of_the_last_update(self):
        runs = []

        async def update():
            get_logger("src.commands.start").info("command /start", event="command")
            # APScheduler starts a job in the context of whoever woke the scheduler last, often an update
            runs.append(asyncio.create_task(self.run_job(self.check, "check_notify_list")))

        await InteractionProcessor(1, fake_account_for).process_update(message_from(123456789, "Wouter"), update())
        await runs[0]

        command, own, library = self.read(MAIN)
        for line in own, library:
            self.assertRegex(line["interaction_id"], CODE)
            self.assertNotEqual(line["interaction_id"], command["interaction_id"])
            self.assertEqual(line["job"], "check_notify_list")
            self.assertFalse({"user_id", "account", "tg_name"} & line.keys())
        self.assertEqual(own["interaction_id"], library["interaction_id"])

    async def test_every_run_gets_a_new_code(self):
        await self.run_job(self.check, "scan_missing_sonarr")
        await self.run_job(self.check, "scan_missing_sonarr")

        first, _, second, _ = self.read(MAIN)
        self.assertNotEqual(first["interaction_id"], second["interaction_id"])
        self.assertEqual(first["job"], second["job"])

    async def test_the_error_handler_gets_the_context_of_the_run_that_failed(self):
        async def error_handler(update: object, context: CallbackContext) -> None:
            get_logger("src.bot").error("job failed", exc_info=context.error)

        async def failing(context: CallbackContext) -> None:
            get_logger("src.commands.schedule").info("checked 14 items")
            raise RuntimeError("Sonarr broke")

        self.application.add_error_handler(error_handler)
        with warnings.catch_warnings():
            # Only in this test: PTB warns that the application, which it starts the error_handler on, is not running
            warnings.filterwarnings("ignore", message="Tasks created via `Application.create_task`", category=PTBUserWarning)
            await self.run_job(failing, "check_notify_list")

        own, error = self.read(MAIN)
        self.assertEqual(error["exc_type"], "RuntimeError")
        self.assertEqual(error["interaction_id"], own["interaction_id"])
        self.assertEqual(error["job"], "check_notify_list")


class BotJobsTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ The jobs that src/bot.py registers: each with its own name, and each run guarded """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:30:00+01:00"))

    def bot(self, mode: str) -> Bot:
        """ A bot whose jobs only write which callback ran """

        def job(callback: str):
            async def run(context: CallbackContext) -> None:
                get_logger("src.bot").info(f"ran {callback}")
            return run

        bot = Bot.__new__(Bot)
        bot.mode = mode
        bot.application = Application.builder().token("123:ABC").build()
        bot.publish_command_list = job("publish_command_list")
        bot.notify_admin_startup = job("notify_admin_startup")
        bot.schedule = SimpleNamespace(check_notify_list=job("check_notify_list"))
        bot.sonarr = SimpleNamespace(scan_missing_media=job("sonarr.scan_missing_media"))
        bot.radarr = SimpleNamespace(scan_missing_media=job("radarr.scan_missing_media"))
        bot._register_jobs()
        return bot

    async def run_jobs(self, bot: Bot) -> dict[str, str]:
        """ Runs every job once; per name of a job, the callback that ran """
        for job in bot.application.job_queue.jobs():
            await job.run(bot.application)
        # Only the lines of the jobs: asyncio in debug mode may warn that building the application was slow
        return {line["job"]: line["msg"].removeprefix("ran ") for line in self.read(MAIN) if line["logger"] == "bot"}

    async def test_every_job_runs_under_its_own_name(self):
        self.assertEqual(await self.run_jobs(self.bot("normal")), {
            "publish_command_list": "publish_command_list",
            "notify_admin_startup": "notify_admin_startup",
            "check_notify_list": "check_notify_list",
            "scan_missing_sonarr": "sonarr.scan_missing_media",
            "scan_missing_radarr": "radarr.scan_missing_media",
        })

    async def test_maintenance_mode_only_has_the_jobs_at_the_start(self):
        self.assertEqual(await self.run_jobs(self.bot("maintenance")), {
            "publish_command_list": "publish_command_list",
            "notify_admin_startup": "notify_admin_startup",
        })


class AccountForTest(unittest.IsolatedAsyncioTestCase):
    """ The account name of a user ID, from the user list in data.json """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_json = str(Path(tmp.name) / "data.dev.json")
        Path(self.data_json).write_text(json.dumps({
            "users": {"wouter": "secret", "anna": "secret2"},
            "user_id": {"123456789": "wouter, Wouter", "555": "anna, Ann, Marie", "556": "anna, Anna", "888": "piet, Piet"},
            "blocked_users": {"777": "Sanne", "888": "Piet"},
        }), encoding="utf-8")

    async def test_the_account_name_of_a_user_id_in_the_user_list(self):
        self.assertEqual(await account_for(123456789, self.data_json), "wouter")

    async def test_more_user_ids_share_an_account(self):
        self.assertEqual(await account_for(555, self.data_json), "anna")
        self.assertEqual(await account_for(556, self.data_json), "anna")

    async def test_no_account_for_a_user_id_outside_the_user_list(self):
        self.assertIsNone(await account_for(777, self.data_json))

    async def test_a_blocked_user_id_is_a_bezoeker_even_if_it_is_in_the_user_list(self):
        self.assertIsNone(await account_for(888, self.data_json))


class CodeTest(unittest.TestCase):
    """ The Code of an Interaction """

    def test_a_code_has_six_characters_of_the_alphabet(self):
        codes = {new_code() for _ in range(200)}

        for code in codes:
            self.assertRegex(code, CODE)

        # Random, so 200 codes out of about 887 million are (almost) never the same
        self.assertGreater(len(codes), 190)

    def test_no_code_outside_an_interaction(self):
        self.assertIsNone(current_code())


if __name__ == "__main__":
    unittest.main()
