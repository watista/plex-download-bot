#!/usr/bin/python3

import asyncio
import json
import logging
import os
import tempfile
import unittest
import warnings
from collections import namedtuple
from datetime import datetime
from itertools import chain
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import Chat, Message, Update, User
from telegram.error import BadRequest, Conflict, NetworkError, RetryAfter, TimedOut
from telegram.ext import Application, BaseHandler, CallbackContext, ConversationHandler
from telegram.warnings import PTBUserWarning

from src.bot import Bot
from src.commands.log import LogCommand
from src.faults import Fault, FaultKind
from src.interaction import (InteractionProcessor, JobQueueOutsideInteractions, account_for, current_code, guard,
                             guard_job, guard_task, new_code, tally, working_on)
from src.log import get_logger, setup_logging
from src.telegram_out import DELIVERED, Delivery
from test_log import DEBUG, MAIN, LogFolder


CODE = r"^[23456789abcdefghjkmnpqrstuvwxyz]{6}$"

# The user list of data.json: user ID to account name
ACCOUNTS = {123456789: "wouter", 555: "anna"}

# The counts that the jobs in JobTest register, like those of check_notify_list: two said in msg, two only as fields
NOTIFY_COUNTS = {"items": "{n} item{s} checked", "sent": "{n} message{s} sent", "not_delivered": None, "skipped": None}


async def fake_account_for(user_id: int) -> str | None:
    """ account_for on a fake user list """
    return ACCOUNTS.get(user_id)


def message_from(user_id: int, first_name: str, text: str = "/start") -> Update:
    """ An update with a private message of this Telegram user """
    user = User(user_id, first_name, is_bot=False)
    return Update(1, message=Message(1, datetime.now(), Chat(user_id, Chat.PRIVATE), from_user=user, text=text))


class FakeSend:
    """ The verzendfunctie: keeps every message, and answers per message with a Delivery or an exception """

    def __init__(self, *answers: Delivery | Exception):
        self.messages = []
        self._answers = list(answers)

    async def __call__(self, chat_id, text: str, fmt: str | None, silent: bool = False) -> Delivery:
        self.messages.append(SimpleNamespace(chat_id=chat_id, text=text, fmt=fmt, silent=silent))
        answer = self._answers.pop(0) if self._answers else DELIVERED
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeFaults:
    """ The meldfunctie: keeps every Fout it gets with how it came, and answers report() with known. Keeps the
    services of ok() and the checks of fixed() too; ok raises ok_error, when there is one. """

    def __init__(self, known: bool = True, ok_error: Exception | None = None):
        self.known = known
        self.reports = []
        self.oks = []
        self.fixes = []
        self._ok_error = ok_error

    async def report(self, fault: Fault, user_told: bool = False, continued: str | None = None, *,
                     outside_wrapper: bool = False) -> bool:
        self.reports.append(SimpleNamespace(fault=fault, user_told=user_told, continued=continued,
                                            outside_wrapper=outside_wrapper, code=current_code()))
        return self.known

    async def ok(self, service: str) -> None:
        self.oks.append(service)
        if self._ok_error is not None:
            raise self._ok_error

    async def fixed(self, service: str, check: str, item: int | str | None, msg: str) -> None:
        self.fixes.append(SimpleNamespace(service=service, check=check, item=item, msg=msg))


def raising(error: Exception):
    """ A handler that raises this exception """

    async def media_option(update: Update, context: CallbackContext) -> int:
        raise error

    return media_option


def raising_job(error: Exception):
    """ A job that raises this exception """

    async def check_notify_list(context: CallbackContext) -> None:
        raise error

    return check_notify_list


def all_handlers(application: Application) -> list[BaseHandler]:
    """ Every handler of the application, with the handlers in a Gesprek instead of the Gesprek itself """
    handlers = []

    def add(handler: BaseHandler) -> None:
        if isinstance(handler, ConversationHandler):
            for inner in [*handler.entry_points, *chain.from_iterable(handler.states.values()), *handler.fallbacks]:
                add(inner)
        else:
            handlers.append(handler)

    for handler in chain.from_iterable(application.handlers.values()):
        add(handler)
    return handlers


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


class GuardTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ guard: a Fout in a handler ends the Gesprek with a Foutmelding, with a fake meldfunctie and verzendfunctie """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))
        self.faults = FakeFaults()
        self.send = FakeSend()

    async def handle(self, callback) -> tuple[object, str]:
        """ callback, guarded, as the handler of a message of anna: what it gives back, and the Code of the update """
        update = message_from(555, "Anna")
        seen = {}

        async def process():
            seen["state"] = await guard(callback, self.faults, self.send)(update, SimpleNamespace())
            seen["code"] = current_code()

        await InteractionProcessor(1, fake_account_for).process_update(update, process())
        return seen["state"], seen["code"]

    async def test_a_fault_ends_the_gesprek_with_an_error_message_that_has_the_code(self):
        state, code = await self.handle(raising(Fault.bug(what="No media state matched")))

        self.assertEqual(state, ConversationHandler.END)
        [report] = self.faults.reports
        self.assertEqual((report.fault.what, report.user_told, report.outside_wrapper, report.code),
                         ("No media state matched", True, False, code))
        [message] = self.send.messages
        self.assertEqual((message.chat_id, message.fmt), (555, "HTML"))
        self.assertEqual(message.text, "\n".join([
            "<b>😵 Oeps, daar ging iets fout</b>",
            "",
            "De serverbeheerder is hiervan op de hoogte. Stuur /start om opnieuw te beginnen.",
            "",
            f"Code: <code>{code}</code>",
        ]))

    async def test_when_the_beheerder_does_not_know_the_user_can_try_again_later(self):
        self.faults.known = False

        _, code = await self.handle(raising(Fault.bug(what="No media state matched")))

        [message] = self.send.messages
        self.assertNotIn("op de hoogte", message.text)
        self.assertIn("\n\nProbeer het later nog eens. Stuur /start om opnieuw te beginnen.\n\n", message.text)
        self.assertTrue(message.text.endswith(f"\nCode: <code>{code}</code>"))

    async def test_the_user_text_of_the_fault_says_what_went_wrong(self):
        fault = Fault.setup(service="radarr", what="No disk with 150 GB free", check="disk_space",
                            user_text="Er is op dit moment een probleem met de opslag van de Plęx server <& co>")

        await self.handle(raising(fault))

        self.assertTrue(self.send.messages[0].text.startswith(
            "<b>😵 Er is op dit moment een probleem met de opslag van de Plęx server &lt;&amp; co&gt;</b>\n\n"))

    async def test_without_a_user_text_a_sentence_per_kind(self):
        faults = [Fault.bug(what="No media state matched"),
                  Fault.disruption(service="radarr", what="Radarr is not responding"),
                  Fault.setup(service="sonarr", what="Carrie has no path in Sonarr", check="series_path", item=1418)]

        for fault in faults:
            await self.handle(raising(fault))

        self.assertEqual([message.text.split("\n")[0] for message in self.send.messages], [
            "<b>😵 Oeps, daar ging iets fout</b>",
            "<b>😵 Een onderdeel van de Plęx server reageert op dit moment niet</b>",
            "<b>😵 Er is een probleem met de inrichting van de Plęx server</b>",
        ])

    async def test_an_unknown_exception_is_a_bug(self):
        error = KeyError("tmdbId")

        state, code = await self.handle(raising(error))

        self.assertEqual(state, ConversationHandler.END)
        [report] = self.faults.reports
        self.assertEqual((report.fault.kind, report.fault.what, report.user_told), (FaultKind.BUG, "Unexpected exception", True))
        self.assertIs(report.fault.__cause__, error)
        [message] = self.send.messages
        self.assertTrue(message.text.endswith(f"\nCode: <code>{code}</code>"))

    async def test_formatting_that_telegram_rejects_is_a_bug(self):
        # A BadRequest is a NetworkError of PTB, but Telegram did answer
        await self.handle(raising(BadRequest("Can't parse entities: unsupported start tag \"x\" at byte offset 0")))

        [report] = self.faults.reports
        self.assertEqual(report.fault.kind, FaultKind.BUG)
        self.assertEqual(len(self.send.messages), 1)

    async def test_no_error_message_while_telegram_is_not_responding(self):
        errors = [NetworkError("httpx.ConnectError: All connection attempts failed"), TimedOut(), RetryAfter(30),
                  Fault.disruption(service="telegram", what="Telegram is not responding", reason="Timed out")]

        states = [(await self.handle(raising(error)))[0] for error in errors]

        self.assertEqual(states, [ConversationHandler.END] * 4)
        self.assertEqual([(report.fault.kind, report.fault.service, report.user_told) for report in self.faults.reports],
                         [(FaultKind.DISRUPTION, "telegram", False)] * 4)
        self.assertEqual(self.send.messages, [])

    async def test_a_callback_that_fails_before_it_runs_keeps_its_traceback(self):
        # Not a coroutine function, so awaiting what it gives back fails in the wrapper itself
        def media_option(update: Update, context: CallbackContext) -> int:
            return 7

        await self.handle(media_option)

        [report] = self.faults.reports
        self.assertIsInstance(report.fault.__cause__, TypeError)
        self.assertIsNotNone(report.fault.__cause__.__traceback__)

    async def test_a_handler_without_a_fout_gives_back_its_own_state(self):
        async def media_option(update: Update, context: CallbackContext) -> int:
            return 7

        state, _ = await self.handle(media_option)

        self.assertEqual(state, 7)
        self.assertEqual((self.faults.reports, self.send.messages), ([], []))

    async def test_telegram_not_responding_to_the_error_message_is_an_attempt_of_a_disruption(self):
        self.send = FakeSend(Fault.disruption(service="telegram", what="Telegram is not responding", reason="Timed out"))

        state, _ = await self.handle(raising(Fault.bug(what="No media state matched")))

        self.assertEqual(state, ConversationHandler.END)
        self.assertEqual([(report.fault.kind, report.fault.service) for report in self.faults.reports],
                         [(FaultKind.BUG, None), (FaultKind.DISRUPTION, "telegram")])

    async def test_an_error_message_that_is_not_delivered_is_a_warning(self):
        self.send = FakeSend(Delivery("Forbidden: bot was blocked by the user"))

        _, code = await self.handle(raising(Fault.bug(what="No media state matched")))

        [line] = self.read(MAIN)
        self.assertEqual((line["level"], line["msg"], line["reason"], line["interaction_id"]),
                         ("WARNING", "error message not delivered: Forbidden: bot was blocked by the user",
                          "Forbidden: bot was blocked by the user", code))


class JobTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ Every run of a job is an Interaction of its own, run the way PTB runs a job """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:30:00+01:00"))
        self.application = Application.builder().token("123:ABC").build()
        self.faults = FakeFaults()

    async def run_job(self, callback, name: str, seconds: float = 0.1, **registered) -> None:
        """ One run of a job that takes this many seconds, registered the way src/bot.py does it, with the counts and
        done it registers; the scheduler itself does not run """
        job = self.application.job_queue.run_once(guard_job(callback, self.faults, **registered), when=3600, name=name)
        with patch("src.interaction.monotonic", side_effect=[1000.0, 1000.0 + seconds]):
            await job.run(self.application)

    def own(self) -> list[dict]:
        """ The lines of the run in the main file without its line job_finished, own and of libraries """
        return [line for line in self.read(MAIN) if line.get("event") != "job_finished"]

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

        command, own, library = self.own()
        for line in own, library:
            self.assertRegex(line["interaction_id"], CODE)
            self.assertNotEqual(line["interaction_id"], command["interaction_id"])
            self.assertEqual(line["job"], "check_notify_list")
            self.assertFalse({"user_id", "account", "tg_name"} & line.keys())
        self.assertEqual(own["interaction_id"], library["interaction_id"])

    async def test_every_run_gets_a_new_code(self):
        await self.run_job(self.check, "scan_missing_sonarr")
        await self.run_job(self.check, "scan_missing_sonarr")

        first, _, second, _ = self.own()
        self.assertNotEqual(first["interaction_id"], second["interaction_id"])
        self.assertEqual(first["job"], second["job"])

    async def test_a_fault_in_a_job_goes_to_the_meldfunctie_and_stops_the_run(self):
        async def failing(context: CallbackContext) -> None:
            get_logger("src.commands.schedule").info("checked 14 items")
            raise Fault.bug(what="No media state matched")
            get_logger("src.commands.schedule").info("checked 15 items")

        await self.run_job(failing, "check_notify_list")

        [own] = self.own()
        [report] = self.faults.reports
        self.assertEqual((report.fault.what, report.user_told, report.code),
                         ("No media state matched", False, own["interaction_id"]))

    async def test_an_unknown_exception_in_a_job_is_a_bug(self):
        error = RuntimeError("Sonarr broke")

        await self.run_job(raising_job(error), "scan_missing_sonarr")

        [report] = self.faults.reports
        self.assertEqual((report.fault.kind, report.fault.what), (FaultKind.BUG, "Unexpected exception"))
        self.assertIs(report.fault.__cause__, error)

    async def test_the_error_handler_gets_the_context_of_a_run_whose_wrapper_failed(self):
        async def error_handler(update: object, context: CallbackContext) -> None:
            get_logger("src.bot").error("job failed", exc_info=context.error)

        async def failing(context: CallbackContext) -> None:
            get_logger("src.commands.schedule").info("checked 14 items")
            raise RuntimeError("Sonarr broke")

        # The meldfunctie itself fails, like when faults.json cannot be read
        self.faults.report = AsyncMock(side_effect=PermissionError("faults.json"))
        self.application.add_error_handler(error_handler)
        with warnings.catch_warnings():
            # Only in this test: PTB warns that the application, which it starts the error_handler on, is not running
            warnings.filterwarnings("ignore", message="Tasks created via `Application.create_task`", category=PTBUserWarning)
            await self.run_job(failing, "check_notify_list")

        # The run still ends with its line, before error_handler gets the exception of the wrapper
        own, finished, error = self.read(MAIN)
        self.assertEqual((finished["event"], finished["outcome"]), ("job_finished", "stopped"))
        self.assertEqual(error["exc_type"], "PermissionError")
        self.assertEqual(error["interaction_id"], own["interaction_id"])
        self.assertEqual(error["job"], "check_notify_list")

    async def test_a_run_ends_with_job_finished_with_its_counts(self):
        async def check_notify_list(context: CallbackContext) -> None:
            get_logger("src.commands.schedule").info("checked 14 items")
            tally("items", 14)
            tally("sent")
            tally("sent")

        await self.run_job(check_notify_list, "check_notify_list", seconds=4.21, counts=NOTIFY_COUNTS)

        own, finished = self.read(MAIN)
        self.assertEqual(list(finished), ["ts", "level", "event", "msg", "outcome", "duration_ms", "items", "sent",
                                          "not_delivered", "skipped", "interaction_id", "job", "logger", "src"])
        self.assertEqual((finished["level"], finished["event"]), ("INFO", "job_finished"))
        self.assertEqual(finished["msg"], "check_notify_list finished in 4.2 s: 14 items checked, 2 messages sent")
        self.assertEqual((finished["outcome"], finished["duration_ms"]), ("ok", 4210))
        # A count that the run did not keep is 0
        self.assertEqual([finished[name] for name in ("items", "sent", "not_delivered", "skipped")], [14, 2, 0, 0])
        self.assertEqual((finished["interaction_id"], finished["job"]), (own["interaction_id"], "check_notify_list"))
        self.assertEqual(finished["logger"], "interaction")

    async def test_a_run_that_a_fout_stopped_ends_with_job_finished_with_the_counts_until_then(self):
        async def check_notify_list(context: CallbackContext) -> None:
            tally("items", 6)
            tally("sent")
            raise Fault.disruption(service="radarr", what="Radarr is not responding", http_status=503)
            tally("items")

        await self.run_job(check_notify_list, "check_notify_list", seconds=1.2, counts=NOTIFY_COUNTS)

        [finished] = self.read(MAIN)
        self.assertEqual(finished["msg"], "check_notify_list stopped after 1.2 s: 6 items checked, 1 message sent")
        self.assertEqual((finished["outcome"], finished["duration_ms"]), ("stopped", 1200))
        self.assertEqual([finished[name] for name in ("items", "sent", "not_delivered", "skipped")], [6, 1, 0, 0])
        self.assertEqual(len(self.faults.reports), 1)

    async def test_a_count_that_is_kept_but_not_registered_is_still_in_the_line(self):
        async def run(context: CallbackContext) -> None:
            tally("not_delivered")

        await self.run_job(run, "check_notify_list")

        [finished] = self.read(MAIN)
        self.assertEqual((finished["not_delivered"], finished["msg"]), (1, "check_notify_list finished in 0.1 s"))

    async def test_a_run_that_finished_says_what_it_did(self):
        await self.run_job(self.nothing, "check_transmission", seconds=0.2, done="Transmission reachable")
        await self.run_job(raising_job(Fault.disruption(service="transmission", what="Transmission is not responding")),
                           "check_transmission", seconds=0.2, done="Transmission reachable")

        self.assertEqual([line["msg"] for line in self.lines("job_finished")], [
            "check_transmission finished in 0.2 s: Transmission reachable",
            "check_transmission stopped after 0.2 s",
        ])

    async def test_a_run_without_counts_only_says_how_long_it_took(self):
        await self.run_job(self.nothing, "publish_command_list")

        [finished] = self.read(MAIN)
        self.assertEqual(finished["msg"], "publish_command_list finished in 0.1 s")
        self.assertEqual(list(finished), ["ts", "level", "event", "msg", "outcome", "duration_ms", "interaction_id",
                                          "job", "logger", "src"])

    async def test_one_count_in_the_singular(self):
        async def check_notify_list(context: CallbackContext) -> None:
            tally("items")

        await self.run_job(check_notify_list, "check_notify_list", counts=NOTIFY_COUNTS)

        [finished] = self.read(MAIN)
        self.assertEqual(finished["msg"], "check_notify_list finished in 0.1 s: 1 item checked, 0 messages sent")

    async def test_a_count_in_a_task_of_the_run_counts_for_the_run(self):
        async def check_notify_list(context: CallbackContext) -> None:
            tally("items")
            await asyncio.create_task(self.count_items())
            # working_on gives the run a new context; the counts stay
            working_on({"title": "Dune", "year": 2021, "tmdbId": 438631})
            tally("items")

        await self.run_job(check_notify_list, "check_notify_list", counts=NOTIFY_COUNTS)

        [finished] = self.read(MAIN)
        self.assertEqual(finished["items"], 3)

    @staticmethod
    async def count_items() -> None:
        """ A task of the run that counts one item """
        tally("items")

    @staticmethod
    async def nothing(context: CallbackContext) -> None:
        """ A job that does its work without a line of its own """

    async def test_a_count_outside_an_interaction_is_no_fout(self):
        # Like a Gebruikersbericht outside a run: there is no run to count for
        tally("sent")

        await self.run_job(self.nothing, "check_notify_list", counts=NOTIFY_COUNTS)

        [finished] = self.read(MAIN)
        self.assertEqual(finished["sent"], 0)


class SchedulerTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ The scheduler itself runs outside every Interaction, also when an update woke it """

    async def test_a_job_that_an_update_scheduled_does_not_get_the_context_of_that_update(self):
        setup_logging("dev", "DEBUG", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))
        application = Application.builder().token("123:ABC").job_queue(JobQueueOutsideInteractions()).build()
        await application.job_queue.start()
        self.addAsyncCleanup(application.job_queue.stop)
        ran = asyncio.Event()

        async def timeout(context: CallbackContext) -> None:
            get_logger("src.bot").info("conversation timed out")
            ran.set()

        async def update():
            # Like every step of a conversation, which schedules its timeout and so wakes the scheduler
            application.job_queue.run_once(timeout, when=0.1, name="timeout")

        await InteractionProcessor(1, fake_account_for).process_update(message_from(123456789, "Wouter"), update())
        await asyncio.wait_for(ran.wait(), timeout=5)

        lines = [line for line in self.read(DEBUG) if line["logger"] in ("bot", "apscheduler.executors.default")]
        self.assertEqual([line["msg"].split(" (")[0] for line in lines],
                         ['Running job "timeout', "conversation timed out"])
        for line in lines:
            self.assertFalse({"user_id", "account", "tg_name", "interaction_id"} & line.keys())


class BotJobsTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ The jobs that src/bot.py registers: each with its own name, and each run guarded """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:30:00+01:00"))

    def bot(self, mode: str, failing: str | None = None) -> Bot:
        """ A bot whose jobs only write which callback ran; the failing one raises instead """

        def job(callback: str):
            async def run(context: CallbackContext) -> None:
                if callback == failing:
                    raise RuntimeError(f"{callback} broke")
                get_logger("src.bot").info(f"ran {callback}")
            return run

        bot = Bot.__new__(Bot)
        bot.mode = mode
        bot.application = Application.builder().token("123:ABC").build()
        bot.faults = FakeFaults()
        bot.publish_command_list = job("publish_command_list")
        bot.notify_admin_startup = job("notify_admin_startup")
        bot.schedule = SimpleNamespace(check_notify_list=job("check_notify_list"),
                                       check_transmission=job("check_transmission"))
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
            "check_transmission": "check_transmission",
            "scan_missing_sonarr": "sonarr.scan_missing_media",
            "scan_missing_radarr": "radarr.scan_missing_media",
        })

    async def test_maintenance_mode_only_has_the_jobs_at_the_start(self):
        self.assertEqual(await self.run_jobs(self.bot("maintenance")), {
            "publish_command_list": "publish_command_list",
            "notify_admin_startup": "notify_admin_startup",
        })

    async def test_a_job_that_fails_goes_to_the_meldfunctie_of_the_bot(self):
        bot = self.bot("normal", failing="sonarr.scan_missing_media")

        ran = await self.run_jobs(bot)

        self.assertNotIn("scan_missing_sonarr", ran)
        [report] = bot.faults.reports
        self.assertEqual(str(report.fault.__cause__), "sonarr.scan_missing_media broke")

    async def test_every_run_ends_with_one_job_finished(self):
        bot = self.bot("normal", failing="sonarr.scan_missing_media")

        with patch("src.interaction.monotonic", side_effect=[0.0, 0.3] * 6):
            await self.run_jobs(bot)

        # Per run its lines, the last one job_finished, and no other job_finished
        runs = {}
        for line in self.read(MAIN):
            if "interaction_id" in line:
                runs.setdefault(line["interaction_id"], []).append(line.get("event"))
        self.assertEqual(len(runs), 6)
        for events in runs.values():
            self.assertEqual((events[-1], events.count("job_finished")), ("job_finished", 1))

        finished = {line["job"]: line for line in self.lines("job_finished")}
        self.assertEqual({job: line["msg"] for job, line in finished.items()}, {
            "publish_command_list": "publish_command_list finished in 0.3 s",
            "notify_admin_startup": "notify_admin_startup finished in 0.3 s",
            "check_notify_list": "check_notify_list finished in 0.3 s: 0 items checked, 0 messages sent",
            "check_transmission": "check_transmission finished in 0.3 s: Transmission reachable",
            "scan_missing_sonarr": "scan_missing_sonarr stopped after 0.3 s",
            "scan_missing_radarr": "scan_missing_radarr finished in 0.3 s: missing search started",
        })
        self.assertEqual([finished["check_notify_list"][name] for name in ("items", "sent", "not_delivered", "skipped")],
                         [0, 0, 0, 0])


# A callback as the fake guard of BotHandlersTest gives it back: wrapped, with what it was wrapped with
Guarded = namedtuple("Guarded", "callback faults send")


class BotHandlersTest(unittest.TestCase):
    """ The handlers that src/bot.py registers: every callback guarded, once """

    def bot(self, mode: str) -> Bot:
        """ A bot with fake commands, whose handlers are registered with a fake guard """
        bot = Bot.__new__(Bot)
        bot.mode = mode
        bot.application = Application.builder().token("123:ABC").build()
        bot.allowed_users = [123456789]
        bot.account_for = fake_account_for
        bot.faults = FakeFaults()
        bot.telegram = SimpleNamespace(send=FakeSend())
        for commands in ("function", "privacy", "help", "maintenance", "start", "account", "message", "serie", "movie",
                         "subscribe"):
            setattr(bot, commands, MagicMock())
        bot.log_command = LogCommand("dev", "log", "data.dev.json", "thuisserver", bot.allowed_users, bot.telegram.send)
        with patch("src.bot.guard", side_effect=Guarded):
            bot._register_handlers()
        return bot

    def test_every_callback_is_guarded_once(self):
        for mode in ("normal", "maintenance"):
            with self.subTest(mode=mode):
                bot = self.bot(mode)

                handlers = all_handlers(bot.application)

                # Not just the handful of handlers of the application: also every handler inside the Gesprek
                self.assertGreater(len(handlers), 40)
                for handler in handlers:
                    self.assertIsInstance(handler.callback, Guarded)
                    self.assertNotIsInstance(handler.callback.callback, Guarded)
                    self.assertIs(handler.callback.faults, bot.faults)
                    self.assertIs(handler.callback.send, bot.telegram.send)


class ErrorHandlerTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ error_handler: the safety net behind the wrappers """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))
        self.bot = Bot.__new__(Bot)
        self.bot.mode = "normal"
        self.bot.faults = FakeFaults()
        self.bot.telegram = SimpleNamespace(send=FakeSend())

    @staticmethod
    def context(error: Exception, job: str | None = None, coroutine=None) -> SimpleNamespace:
        """ The context PTB hands error_handler: the error, and the job or task it came from """
        return SimpleNamespace(error=error, job=job and SimpleNamespace(name=job), coroutine=coroutine)

    async def test_an_exception_of_an_update_outside_the_wrapper_is_a_bug_with_an_error_message(self):
        update = message_from(555, "Anna")
        error = AttributeError("'NoneType' object has no attribute 'data'")
        seen = {}

        async def process():
            # PTB calls error_handler in the processing of the update itself
            await self.bot.error_handler(update, self.context(error))
            seen["code"] = current_code()

        await InteractionProcessor(1, fake_account_for).process_update(update, process())

        [report] = self.bot.faults.reports
        self.assertEqual((report.fault.kind, report.outside_wrapper, report.user_told), (FaultKind.BUG, True, True))
        self.assertIs(report.fault.__cause__, error)
        [message] = self.bot.telegram.send.messages
        self.assertEqual(message.chat_id, 555)
        self.assertTrue(message.text.endswith(f"\nCode: <code>{seen['code']}</code>"))

    async def test_without_an_update_there_is_no_error_message(self):
        # A job whose wrapper failed, and a task of create_task
        await self.bot.error_handler(None, self.context(PermissionError("faults.json"), job="check_notify_list"))
        await self.bot.error_handler(None, self.context(RuntimeError("heartbeat"), coroutine=object()))

        self.assertEqual([(report.outside_wrapper, report.user_told) for report in self.bot.faults.reports],
                         [(True, False), (True, False)])
        self.assertEqual(self.bot.telegram.send.messages, [])

    async def test_an_error_without_an_update_job_or_task_that_polling_does_not_give_is_a_bug(self):
        # Like PTB writing bot_state.pkl, which hands error_handler its error without an update, a job or a task. A
        # BadRequest is a NetworkError too, but Telegram did answer.
        for error in PermissionError("bot_state.pkl"), BadRequest("Bad Request: invalid offset"):
            await self.bot.error_handler(None, self.context(error))

        self.assertEqual([(report.fault.kind, report.outside_wrapper, report.user_told)
                          for report in self.bot.faults.reports], [(FaultKind.BUG, True, False)] * 2)

    async def test_a_network_error_of_polling_is_a_failed_attempt_of_a_disruption_of_telegram(self):
        errors = NetworkError("httpx.ConnectError: [Errno -3] Temporary failure in name resolution"), NetworkError(
            "Bad Gateway")
        for error in errors:
            await self.bot.error_handler(None, self.context(error))

        self.assertEqual([(report.fault.kind, report.fault.service, report.fault.reason, report.code, report.user_told,
                           report.outside_wrapper) for report in self.bot.faults.reports], [
            (FaultKind.DISRUPTION, "telegram", "httpx.ConnectError: [Errno -3] Temporary failure in name resolution",
             None, False, False),
            (FaultKind.DISRUPTION, "telegram", "Bad Gateway", None, False, False),
        ])
        self.assertEqual([report.fault.__cause__ for report in self.bot.faults.reports], list(errors))
        self.assertEqual(self.bot.telegram.send.messages, [])

    async def test_a_conflict_of_polling_is_one_warning_without_a_fault(self):
        await self.bot.error_handler(None, self.context(Conflict("terminated by other getUpdates request; make sure "
                                                                 "that only one bot instance is running")))

        self.assertEqual(self.bot.faults.reports, [])
        [line] = self.read(MAIN)
        self.assertEqual((line["level"], line["msg"]), ("WARNING", "Telegram Conflict: another bot instance is "
                                                                   "polling"))
        self.assertNotIn("fault", line)
        # Only the standby bot tells the Beheerder
        self.assertEqual(self.bot.telegram.send.messages, [])


class GuardTaskTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ guard_task: the heartbeat, which a Bug does not stop for good """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.faults = FakeFaults()
        self.slept = []

    async def sleep(self, seconds: float) -> None:
        """ asyncio.sleep, without waiting """
        self.slept.append(seconds)

    async def test_the_heartbeat_starts_again_60_seconds_after_a_bug(self):
        error = OverflowError("port must be 0-65535.")
        starts = []

        async def heartbeat() -> None:
            starts.append(list(self.slept))
            if len(starts) < 3:
                raise error

        await guard_task(heartbeat, self.faults, sleep=self.sleep)

        self.assertEqual(starts, [[], [60], [60, 60]])
        # A Bug outside an Interaction: its Code is one of its own, which the meldfunctie gives it
        self.assertEqual([(report.fault.kind, report.fault.what, report.user_told, report.code)
                          for report in self.faults.reports],
                         [(FaultKind.BUG, "Unexpected exception", False, None)] * 2)
        self.assertIs(self.faults.reports[0].fault.__cause__, error)
        # The Fout is that of the heartbeat, not of the wrapper
        self.assertEqual(error.__traceback__.tb_frame.f_code.co_name, "heartbeat")

    async def test_a_fault_in_the_heartbeat_goes_to_the_meldfunctie_as_it_is(self):
        fault = Fault.disruption(service="fallback", what="The fallback host is not responding")
        starts = []

        async def heartbeat() -> None:
            starts.append(None)
            if len(starts) == 1:
                raise fault

        await guard_task(heartbeat, self.faults, sleep=self.sleep)

        [report] = self.faults.reports
        self.assertIs(report.fault, fault)

    async def test_a_heartbeat_that_ends_is_not_started_again(self):
        async def heartbeat() -> None:
            """ Like a heartbeat without HEARTBEAT_TARGET_HOST """

        await guard_task(heartbeat, self.faults, sleep=self.sleep)

        self.assertEqual((self.slept, self.faults.reports), ([], []))

    async def test_cancelling_it_is_no_fout(self):
        started = asyncio.Event()

        async def heartbeat() -> None:
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(guard_task(heartbeat, self.faults))
        await started.wait()
        task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.faults.reports, [])


class HeartbeatTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ The heartbeat to the watcher on the fallback host, which takes over when it stops coming """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))
        self.bot = Bot.__new__(Bot)
        self.bot.faults = FakeFaults()

    async def watcher(self) -> int:
        """ The port of a watcher on this host, which takes heartbeats """
        server = await asyncio.start_server(lambda reader, writer: writer.close(), "127.0.0.1", 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        return server.sockets[0].getsockname()[1]

    async def no_watcher(self) -> int:
        """ A port on this host that nothing listens on """
        server = await asyncio.start_server(lambda reader, writer: writer.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        server.close()
        await server.wait_closed()
        return port

    async def test_a_heartbeat_that_arrives_ends_a_disruption_of_the_fallback_host(self):
        await self.bot._heartbeat("127.0.0.1", await self.watcher())

        self.assertEqual((self.bot.faults.oks, self.bot.faults.reports), (["fallback"], []))

    async def test_a_heartbeat_that_fails_is_an_attempt_of_a_disruption_of_the_fallback_host(self):
        await self.bot._heartbeat("127.0.0.1", await self.no_watcher())

        [report] = self.bot.faults.reports
        self.assertEqual((report.fault.kind, report.fault.service, report.fault.what, report.code),
                         (FaultKind.DISRUPTION, "fallback", "The fallback host is not responding", None))
        self.assertIsInstance(report.fault.__cause__, ConnectionRefusedError)
        self.assertEqual(self.bot.faults.oks, [])
        # The meldfunctie writes the line of every attempt, short after the first
        self.assertEqual(self.read(MAIN), [])

    async def test_without_heartbeat_target_host_the_heartbeat_is_off_with_a_line(self):
        with patch.dict(os.environ, {"HEARTBEAT_TARGET_HOST": ""}):
            self.assertIsNone(await self.bot._heartbeat_target())

        [line] = self.read(MAIN)
        self.assertEqual((line["level"], line["msg"]), ("INFO", "heartbeat off: HEARTBEAT_TARGET_HOST is not set"))
        self.assertEqual((self.bot.faults.reports, self.bot.faults.fixes), ([], []))

    async def test_a_wrong_heartbeat_target_port_is_an_inrichtingsfout(self):
        for port in "98x76", "0", "65536":
            settings = {"HEARTBEAT_TARGET_HOST": "fallback.example.com", "HEARTBEAT_TARGET_PORT": port}
            with patch.dict(os.environ, settings):
                self.assertIsNone(await self.bot._heartbeat_target())

        self.assertEqual([(report.fault.kind, report.fault.service, report.fault.check, report.fault.item,
                           report.fault.reason, report.continued) for report in self.bot.faults.reports], [
            (FaultKind.SETUP, "fallback", "setting", "HEARTBEAT_TARGET_PORT", f"{port!r} is not a port number",
             "the bot runs without a heartbeat") for port in ("98x76", "0", "65536")])
        self.assertEqual(self.bot.faults.reports[0].fault.what, "HEARTBEAT_TARGET_PORT is not a port number")
        self.assertEqual(self.bot.faults.fixes, [])

    async def test_a_right_heartbeat_target_port_sets_the_inrichtingsfout_right(self):
        with patch.dict(os.environ, {"HEARTBEAT_TARGET_HOST": "fallback.example.com", "HEARTBEAT_TARGET_PORT": "9876",
                                     "HEARTBEAT_INTERVAL": "5"}):
            self.assertEqual(await self.bot._heartbeat_target(), ("fallback.example.com", 9876, 5))

        self.assertEqual(self.bot.faults.reports, [])
        [fixed] = self.bot.faults.fixes
        self.assertEqual((fixed.service, fixed.check, fixed.item, fixed.msg), (
            "fallback", "setting", "HEARTBEAT_TARGET_PORT", "HEARTBEAT_TARGET_PORT is a port number again"))

    async def test_stopping_the_bot_reports_an_exception_that_stopped_the_heartbeat(self):
        bot = self.bot
        bot.args = SimpleNamespace(env="dev")
        bot.mode = "normal"
        bot.primary_name, bot.fallback_name = "primary", "fallback"
        bot.telegram = SimpleNamespace(send_admin_message=AsyncMock(return_value=DELIVERED))
        error = PermissionError("faults.json")

        async def heartbeat() -> None:
            # Like guard_task when the meldfunctie itself fails
            raise error

        bot._heartbeat_task = asyncio.create_task(heartbeat())
        await asyncio.sleep(0)
        with patch.dict(os.environ, {"HEARTBEAT_TARGET_HOST": ""}):
            await bot._post_stop(MagicMock())

        [report] = bot.faults.reports
        self.assertEqual((report.fault.kind, report.continued), (FaultKind.BUG, "went on stopping the bot"))
        self.assertIs(report.fault.__cause__, error)
        # The rest of the stop goes on
        bot.telegram.send_admin_message.assert_awaited_once()
        self.assertEqual([line["event"] for line in self.read(MAIN)], ["bot_stopped"])


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
