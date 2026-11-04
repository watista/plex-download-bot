#!/usr/bin/python3

import asyncio
import inspect
import json
import re
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from src.faults import Fault, FaultKind, FaultReporter, admin_message_html
from src.interaction import Interaction, InteractionProcessor, current_code, guard_job, working_on
from src.log import PROJECT_DIR, setup_logging
from src.telegram_out import DELIVERED, Delivery
from test_interaction import CODE, message_from
from test_log import MAIN, LogFolder
from test_telegram_out import ADMIN_CHAT


DUNE = {"title": "Dune: Part Two", "year": 2024, "tmdbId": 693134}

# The user list of data.json: user ID to account name, with anna of the example in the spec
ACCOUNTS = {123456789: "anna", 555: "anna"}


async def fake_account_for(user_id: int) -> str | None:
    """ account_for on a fake user list """
    return ACCOUNTS.get(user_id)


def compiled_at(path: str, line: int, function: str, statement: str, namespace: dict) -> None:
    """ Defines a function in namespace as if it were in this file of the bot, with its one statement at this line """
    source = "\n" * (line - 2) + f"def {function}():\n    {statement}\n"
    exec(compile(source, str(PROJECT_DIR / path), "exec"), namespace)


def refused_in_the_code_of_the_spec() -> Fault:
    """ The Bug of the example in the spec: Radarr refuses a movie request, at the own frames that the example shows """
    namespace = {"Fault": Fault, "DUNE": DUNE}
    compiled_at("src/services/arr.py", 98, "post",
                "raise Fault.bug(what='Radarr refused the movie request', service='radarr', "
                "reason='This movie has already been added', http_status=400, media=DUNE)", namespace)
    compiled_at("src/services/radarr.py", 31, "add_movie", "post()", namespace)
    compiled_at("src/commands/movie.py", 84, "start_download", "add_movie()", namespace)
    compiled_at("src/commands/media.py", 242, "media_choice", "start_download()", namespace)
    try:
        namespace["media_choice"]()
    except Fault as fault:
        # Without the frame of this function, which the example does not have
        return fault.with_traceback(fault.__traceback__.tb_next)


def radarr_refused(reason: str = "This movie has already been added", http_status: int = 400) -> Fault:
    """ The Bug of Radarr refusing a movie request, always raised from this one line """
    try:
        raise Fault.bug(what="Radarr refused the movie request", service="radarr", reason=reason,
                        http_status=http_status, details={"monitored": True}, media=DUNE)
    except Fault as fault:
        return fault


def no_state_matched() -> Fault:
    """ Another Bug, raised from another line """
    try:
        raise Fault.bug(what="No media state matched", details={"status": "inCinemas"})
    except Fault as fault:
        return fault


def parse(text: str) -> dict:
    """ Own code that lets a library raise: the innermost own frame """
    return json.loads(text)


def choose(text: str) -> dict:
    """ Own code between the wrapper and parse """
    return parse(text)


def unexpected(text: str) -> Fault:
    """ What the wrapper does with an exception it did not expect: it raises a Bug from it """
    try:
        try:
            choose(text)
        except Exception as e:
            raise Fault.bug(what="Unexpected exception") from e
    except Fault as fault:
        return fault


def library_error() -> ZeroDivisionError:
    """ An exception of a library, without a single own frame in its traceback """
    source = "def a():\n    b()\ndef b():\n    c()\ndef c():\n    d()\ndef d():\n    1 / 0\na()\n"
    try:
        exec(compile(source, "/usr/lib/python3/dist-packages/somelib.py", "exec"), {})
    except ZeroDivisionError as e:
        # Without the frame of this function, which is own code
        return e.with_traceback(e.__traceback__.tb_next)


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


class FakeClock:
    """ The clock of the meldfunctie, which a test moves on """

    def __init__(self, moment: str):
        self.moment = datetime.fromisoformat(moment)

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **delta) -> None:
        self.moment += timedelta(**delta)


class FaultTest(unittest.TestCase):
    """ A Fout in the code: an exception with its kind, made by the constructor of that kind """

    def test_each_constructor_makes_its_kind(self):
        bug = Fault.bug(what="Radarr refused the movie request", service="radarr",
                        reason="This movie has already been added", http_status=400)
        disruption = Fault.disruption(service="telegram", what="Telegram is not responding", reason="Timed out")
        setup = Fault.setup(service="sonarr", what="Carrie has no path in Sonarr", check="series_path", item=1418)

        self.assertEqual([fault.kind for fault in (bug, disruption, setup)],
                         [FaultKind.BUG, FaultKind.DISRUPTION, FaultKind.SETUP])
        self.assertEqual((setup.check, setup.item), ("series_path", 1418))
        self.assertEqual((bug.check, bug.item), (None, None))
        self.assertEqual(str(bug), "Radarr refused the movie request: This movie has already been added")

    def test_the_kind_is_written_as_in_the_field_fault(self):
        self.assertEqual([str(kind) for kind in FaultKind], ["bug", "disruption", "setup"])

    def test_a_setup_fault_needs_a_check(self):
        with self.assertRaises(TypeError):
            Fault.setup(service="sonarr", what="Carrie has no path in Sonarr", item=1418)

    def test_only_a_setup_fault_has_a_check_and_an_item(self):
        with self.assertRaises(TypeError):
            Fault.bug(what="Radarr refused the movie request", check="tmdb_lookup")
        with self.assertRaises(TypeError):
            Fault.disruption(service="radarr", what="Radarr is not responding", item=1418)

    def test_a_disruption_is_always_of_a_service(self):
        with self.assertRaises(TypeError):
            Fault.disruption(what="Radarr is not responding")


class AdminMessageHtmlTest(unittest.TestCase):
    """ The HTML of an admin message about a Fout, from the Fault, the Interaction it happened in and the own frames """

    def test_an_exception_outside_the_wrapper_of_a_visitor(self):
        fault = Fault.bug(what="Unexpected exception")
        fault.__cause__ = AttributeError("'NoneType' object has no attribute 'data'")
        kees = Interaction("p6c2vd", user_id=323456789, tg_name="Kees")

        html = admin_message_html(fault, kees, ["src/commands/help.py:88 in help_choice"], user_told=True,
                                  outside_wrapper=True)

        self.assertEqual(html, "\n".join([
            "🐞 <b>Bug</b> · Unexpected exception",
            "Exception: <code>AttributeError</code>: 'NoneType' object has no attribute 'data'",
            "Visitor: Kees",
            "Caught by error_handler, outside the wrapper",
            "<blockquote expandable><code>src/commands/help.py:88 in help_choice</code>",
            "user_id: 323456789",
            "user told: yes</blockquote>",
            "Code: <code>p6c2vd</code>",
        ]))

    def test_a_repeated_bug_in_a_job_that_continued(self):
        fault = Fault.bug(what="No media state matched",
                          details={"movieFileId": None, "monitored": True, "status": "inCinemas"})
        run = Interaction("w3f8na", job="check_notify_list", media={"title": "Slow Horses", "tvdbId": 288673})

        html = admin_message_html(fault, run, ["src/commands/media.py:333 in media_choice"], user_told=False,
                                  continued="skipped this series", repeat="4× since the last alert (12 Oct 14:02)")

        self.assertEqual(html, "\n".join([
            "🐞 <b>Bug</b> · No media state matched",
            "Job: <code>check_notify_list</code>",
            "Media: Slow Horses",
            "Continued: skipped this series",
            "Repeat: 4× since the last alert (12 Oct 14:02)",
            "<blockquote expandable>movieFileId: None",
            "monitored: True",
            "status: inCinemas",
            "<code>src/commands/media.py:333 in media_choice</code>",
            "tvdb 288673</blockquote>",
            "Code: <code>w3f8na</code>",
        ]))

    def test_the_reason_of_the_service_and_the_exception_the_fault_came_from(self):
        fault = Fault.bug(what="Radarr refused the movie request", service="radarr", reason="Invalid Path",
                          http_status=400)
        fault.__cause__ = ValueError("400, message='Bad Request'")

        html = admin_message_html(fault, Interaction("k7p2qx"), [], user_told=False)

        self.assertEqual(html.splitlines()[1:3], ["Reason: <i>Invalid Path</i> (HTTP 400)",
                                                  "Exception: <code>ValueError</code>: 400, message='Bad Request'"])

    def test_every_value_is_escaped(self):
        fault = Fault.bug(what="Radarr & Sonarr <disagree>", reason="a < b", details={"<query>": "Tom & Jerry"},
                          media={"title": "<Untitled>"})

        html = admin_message_html(fault, Interaction("k7p2qx", user_id=555, account="a&b"), ["src/x.py:1 in <lambda>"],
                          user_told=False)

        for escaped in ("Radarr &amp; Sonarr &lt;disagree&gt;", "<i>a &lt; b</i>", "&lt;query&gt;: Tom &amp; Jerry",
                        "Media: &lt;Untitled&gt;", "User: a&amp;b", "<code>src/x.py:1 in &lt;lambda&gt;</code>"):
            self.assertIn(escaped, html)

    def test_the_reason_and_the_exception_are_cut_at_300_characters(self):
        reason = Fault.bug(what="Radarr refused the movie request", reason="r" * 301)
        exception = Fault.bug(what="Unexpected exception")
        exception.__cause__ = ValueError("e" * 400)

        reason_line = admin_message_html(reason, Interaction("k7p2qx"), [], user_told=False).splitlines()[1]
        exception_line = admin_message_html(exception, Interaction("k7p2qx"), [], user_told=False).splitlines()[1]

        self.assertEqual(reason_line, f"Reason: <i>{'r' * 299}…</i>")
        self.assertEqual(exception_line, f"Exception: <code>ValueError</code>: {'e' * 299}…")

    def test_a_message_that_is_too_long_is_cut_at_the_back_of_its_block(self):
        fault = Fault.bug(what="No media state matched", details={"overview": "&" * 5000})
        anna = Interaction("k7p2qx", user_id=555, account="anna")

        html = admin_message_html(fault, anna, ["src/commands/media.py:333 in media_choice"], user_told=True)

        self.assertLessEqual(len(html), 4096)
        self.assertGreater(len(html), 4000)
        self.assertTrue(html.startswith("🐞 <b>Bug</b> · No media state matched\nUser: anna\n"
                                        "<blockquote expandable>overview: &amp;&amp;"), html[:200])
        self.assertTrue(html.endswith("&amp;\n… truncated, see log</blockquote>\nCode: <code>k7p2qx</code>"),
                        html[-200:])
        # Never half an entity
        self.assertIsNone(re.search(r"&(?!amp;|lt;|gt;)", html))

    def test_a_cut_in_the_own_code_keeps_the_innermost_frames_and_closes_its_tag(self):
        frames = [f"src/commands/media.py:{n} in step_{n}" for n in range(300)]
        anna = Interaction("k7p2qx", user_id=555, account="anna")

        html = admin_message_html(Fault.bug(what="Unexpected exception"), anna, frames, user_told=True)

        self.assertLessEqual(len(html), 4096)
        self.assertIn("<blockquote expandable><code>src/commands/media.py:0 in step_0\n", html)
        self.assertEqual(html.count("<code>"), html.count("</code>"))
        self.assertTrue(html.endswith("</code>\n… truncated, see log</blockquote>\nCode: <code>k7p2qx</code>"),
                        html[-200:])
        self.assertNotIn("user told", html)


class ReportTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ report: the line of every Fout and an admin message about a Bug, with a fake verzendfunctie and a fake clock """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))
        self.clock = FakeClock("2026-11-03T14:05:12+01:00")
        self.state_file = self.folder / "faults.dev.json"
        self.send = FakeSend()

    def reporter(self) -> FaultReporter:
        """ A new meldfunctie on the state file of this test """
        return FaultReporter(self.send, ADMIN_CHAT, self.state_file, now=self.clock)

    async def in_an_update(self, call, user_id: int = 555, first_name: str = "Anna") -> tuple[bool, str]:
        """ call() in an update of this Telegram user, as PTB hands it to the InteractionProcessor: its result and Code """
        seen = {}

        async def handle():
            seen["result"] = await call()
            seen["code"] = current_code()

        await InteractionProcessor(1, fake_account_for).do_process_update(message_from(user_id, first_name), handle())
        return seen["result"], seen["code"]

    def faults(self) -> list[dict]:
        """ The lines of the Fouten themselves in the main file """
        return [line for line in self.read(MAIN) if "fault" in line and line.get("event") != "admin_message_sent"]

    @staticmethod
    def block(text: str) -> list[str]:
        """ The lines of the expandable block of an admin message """
        return re.search(r"<blockquote expandable>(.*)</blockquote>", text, re.DOTALL).group(1).splitlines()

    async def test_the_example_of_the_spec(self):
        reporter = self.reporter()

        _, code = await self.in_an_update(lambda: reporter.report(refused_in_the_code_of_the_spec(), user_told=True),
                                          user_id=123456789)

        # The title becomes a link to Radarr in issue 09
        self.assertEqual(self.send.messages[0].text, "\n".join([
            "🐞 <b>Bug</b> · Radarr refused the movie request",
            "Reason: <i>This movie has already been added</i> (HTTP 400)",
            "User: anna",
            "Media: Dune: Part Two (2024)",
            "<blockquote expandable><code>src/services/arr.py:98 in post",
            "src/services/radarr.py:31 in add_movie",
            "src/commands/movie.py:84 in start_download",
            "src/commands/media.py:242 in media_choice</code>",
            "tmdb 693134",
            "user_id: 123456789",
            "user told: yes</blockquote>",
            f"Code: <code>{code}</code>",
        ]))
        [line] = self.faults()
        self.assertEqual(line["src"], "src/services/arr.py:98 in post")

    async def test_a_bug_alerts_the_beheerder(self):
        reporter = self.reporter()

        told, code = await self.in_an_update(lambda: reporter.report(radarr_refused(), user_told=True))

        self.assertTrue(told)
        [message] = self.send.messages
        self.assertEqual((message.chat_id, message.fmt, message.silent), (ADMIN_CHAT, "HTML", False))
        self.assertEqual(message.text.splitlines()[:4], ["🐞 <b>Bug</b> · Radarr refused the movie request",
                                                         "Reason: <i>This movie has already been added</i> (HTTP 400)",
                                                         "User: anna",
                                                         "Media: Dune: Part Two (2024)"])
        self.assertTrue(message.text.endswith(f"\nCode: <code>{code}</code>"))
        block = self.block(message.text)
        self.assertEqual(block[0], "monitored: True")
        self.assertRegex(block[1], r"^<code>tests/test_faults\.py:\d+ in radarr_refused</code>$")
        self.assertEqual(block[2:], ["tmdb 693134", "user_id: 555", "user told: yes"])

        [sent] = self.lines("admin_message_sent")
        self.assertEqual((sent["level"], sent["msg"], sent["fault"], sent["service"], sent["interaction_id"]),
                         ("INFO", "admin message sent: Bug · Radarr refused the movie request", "bug", "radarr", code))

    async def test_the_full_line_of_a_bug(self):
        reporter = self.reporter()

        _, code = await self.in_an_update(lambda: reporter.report(radarr_refused()))

        # No exc_type: the bot raised the Fault of its own, it did not come from another exception
        [line] = self.faults()
        self.assertEqual(list(line), ["ts", "level", "user_id", "account", "msg", "reason", "http_status", "details",
                                      "media_title", "media_year", "tmdb_id", "fault", "service", "interaction_id",
                                      "logger", "src", "exc"])
        self.assertEqual((line["level"], line["msg"], line["fault"], line["service"], line["interaction_id"]),
                         ("ERROR", "Radarr refused the movie request: This movie has already been added", "bug",
                          "radarr", code))
        self.assertEqual((line["http_status"], line["details"], line["tmdb_id"]), (400, {"monitored": True}, 693134))
        self.assertEqual((line["account"], line["logger"]), ("anna", "faults"))
        self.assertRegex(line["src"], r"^tests/test_faults\.py:\d+ in radarr_refused$")
        self.assertIn("Traceback (most recent call last)", line["exc"])

    async def test_only_an_exception_raised_from_counts_as_the_one_the_fault_came_from(self):
        reporter = self.reporter()
        try:
            {}["missing"]
        except KeyError:
            # The Fault gets the KeyError as its context, but was not raised from it
            fault = no_state_matched()

        await reporter.report(fault)

        [line] = self.faults()
        self.assertNotIn("exc_type", line)
        self.assertEqual(line["msg"], "No media state matched")
        self.assertRegex(line["src"], r"^tests/test_faults\.py:\d+ in no_state_matched$")
        self.assertNotIn("Exception:", self.send.messages[0].text)

    async def test_a_bug_gives_one_admin_message_per_24_hours_per_signature(self):
        reporter = self.reporter()
        told = [await reporter.report(radarr_refused())]

        # The reason does not count: it holds titles
        for hours in 1, 22:
            self.clock.advance(hours=hours)
            told.append(await reporter.report(radarr_refused(reason="Tenet has already been added")))
        self.assertEqual(len(self.send.messages), 1)

        self.clock.advance(hours=1)
        told.append(await reporter.report(radarr_refused()))

        self.assertEqual(told, [True, True, True, True])
        self.assertEqual(len(self.send.messages), 2)
        self.assertIn("Repeat: 3× since the last alert (3 Nov 14:05)", self.send.messages[1].text.splitlines())
        self.assertNotIn("Repeat:", self.send.messages[0].text)

    async def test_another_signature_is_another_bug(self):
        reporter = self.reporter()

        # Another status of a 4xx, another line, another type of exception
        for fault in radarr_refused(), radarr_refused(http_status=404), no_state_matched(), unexpected("{"):
            self.assertTrue(await reporter.report(fault))

        self.assertEqual(len(self.send.messages), 4)

    async def test_a_short_line_between_two_admin_messages(self):
        reporter = self.reporter()
        await reporter.report(radarr_refused())
        for hours in 1, 1, 23:
            self.clock.advance(hours=hours)
            await reporter.report(radarr_refused())

        first, short, shorter, again = self.faults()

        self.assertEqual([short["repeat"], shorter["repeat"]], [1, 2])
        self.assertEqual(list(short), ["ts", "level", "msg", "reason", "http_status", "repeat", "media_title",
                                       "media_year", "tmdb_id", "fault", "service", "interaction_id", "logger", "src"])
        self.assertEqual(short["src"], first["src"])
        for full in first, again:
            self.assertNotIn("repeat", full)
            self.assertEqual((full["details"], full["exc"][:9]), ({"monitored": True}, "Traceback"))

    async def test_the_state_survives_a_new_reporter_on_the_same_file(self):
        await self.reporter().report(radarr_refused())

        self.clock.advance(hours=1)
        self.assertTrue(await self.reporter().report(radarr_refused()))
        self.assertEqual(len(self.send.messages), 1)

        self.clock.advance(hours=23)
        await self.reporter().report(radarr_refused())
        self.assertIn("Repeat: 2× since the last alert (3 Nov 14:05)", self.send.messages[1].text.splitlines())

    async def test_an_unreadable_state_file_starts_without_a_state(self):
        self.state_file.write_text("{", encoding="utf-8")

        self.assertTrue(await self.reporter().report(radarr_refused()))

        self.assertEqual(len(self.send.messages), 1)
        [warning] = [line for line in self.read(MAIN) if line["level"] == "WARNING"]
        self.assertIn("faults.dev.json", warning["msg"])
        self.assertIn("bugs", json.loads(self.state_file.read_text(encoding="utf-8")))

    async def test_the_last_alert_of_another_year_has_its_year(self):
        self.clock = FakeClock("2025-10-31T09:00:00+01:00")
        await self.reporter().report(radarr_refused())

        self.clock.advance(days=368)
        await self.reporter().report(radarr_refused())

        self.assertIn("Repeat: 1× since the last alert (31 Oct 2025 09:00)", self.send.messages[1].text.splitlines())

    async def test_report_gives_false_when_the_admin_message_does_not_arrive(self):
        self.send = FakeSend(Delivery("Forbidden: bot was kicked from the group chat"))
        reporter = self.reporter()

        self.assertFalse(await reporter.report(radarr_refused()))

        # The Beheerder does not know yet, so the next time alerts again, as the first time
        self.clock.advance(minutes=5)
        self.assertTrue(await reporter.report(radarr_refused()))
        self.assertEqual(len(self.send.messages), 2)
        self.assertNotIn("Repeat:", self.send.messages[1].text)
        [warning] = [line for line in self.read(MAIN) if line["level"] == "WARNING"]
        self.assertEqual((warning["msg"], warning["reason"]),
                         ("admin message not delivered: Bug · Radarr refused the movie request: "
                          "Forbidden: bot was kicked from the group chat",
                          "Forbidden: bot was kicked from the group chat"))

    async def test_a_bug_that_comes_again_while_its_admin_message_fails_is_not_held_back(self):
        sent = []

        async def send(chat_id, text: str, fmt: str | None, silent: bool = False) -> Delivery:
            sent.append(text)
            if len(sent) == 1:
                # Meanwhile, a job runs into the same Bug
                await reporter.report(radarr_refused())
                return Delivery("Forbidden: bot was kicked from the group chat")
            return DELIVERED

        reporter = FaultReporter(send, ADMIN_CHAT, self.state_file, now=self.clock)

        self.assertFalse(await reporter.report(radarr_refused()))
        self.clock.advance(minutes=5)
        self.assertTrue(await reporter.report(radarr_refused()))

        self.assertEqual(len(sent), 2)

    async def test_telegram_not_responding_while_sending_is_a_disruption_of_its_own(self):
        self.send = FakeSend(Fault.disruption(service="telegram", what="Telegram is not responding", reason="Timed out"))

        self.assertFalse(await self.reporter().report(radarr_refused()))

        self.assertEqual([(line["level"], line["fault"], line["service"]) for line in self.faults()],
                         [("ERROR", "bug", "radarr"), ("WARNING", "disruption", "telegram")])
        self.assertEqual(self.lines("admin_message_sent"), [])

    async def test_a_disruption_and_a_setup_fault_only_get_their_line_for_now(self):
        try:
            try:
                raise TimeoutError("timed out")
            except TimeoutError as e:
                raise Fault.disruption(service="radarr", what="Radarr is not responding", reason="timed out") from e
        except Fault as fault:
            disruption = fault
        setup = Fault.setup(service="sonarr", what="Carrie has no path in Sonarr", check="series_path", item=1418)
        reporter = self.reporter()

        told = [await reporter.report(disruption)]
        line_number = inspect.currentframe().f_lineno + 1
        told.append(await reporter.report(setup))

        self.assertEqual(told, [False, False])
        self.assertEqual(self.send.messages, [])
        disrupted, wrong = self.faults()
        self.assertEqual((disrupted["level"], disrupted["msg"], disrupted["exc_type"]),
                         ("WARNING", "Radarr is not responding: timed out", "TimeoutError"))
        self.assertRegex(disrupted["src"], r"^tests/test_faults\.py:\d+ in test_a_disruption_and_a_setup_fault")
        self.assertEqual((wrong["level"], wrong["msg"], wrong["fault"], wrong["service"]),
                         ("ERROR", "Carrie has no path in Sonarr", "setup", "sonarr"))
        # Never raised: the line is of the caller
        self.assertEqual(wrong["src"], f"tests/test_faults.py:{line_number} in "
                                       f"test_a_disruption_and_a_setup_fault_only_get_their_line_for_now")
        for line in disrupted, wrong:
            self.assertNotIn("exc", line)
            self.assertNotIn("interaction_id", line)
        self.assertNotIn("exc_type", wrong)

    async def test_the_own_code_of_an_unexpected_exception(self):
        reporter = self.reporter()

        await self.in_an_update(lambda: reporter.report(unexpected("{")))

        [line] = self.faults()
        self.assertRegex(line["src"], r"^tests/test_faults\.py:\d+ in parse$")
        self.assertEqual(line["exc_type"], "JSONDecodeError")
        self.assertTrue(line["msg"].startswith("Unexpected exception: JSONDecodeError: Expecting property name"))
        self.assertIn("The above exception was the direct cause of the following exception", line["exc"])

        [message] = self.send.messages
        self.assertIn("\nException: <code>JSONDecodeError</code>: Expecting property name", message.text)
        frames = re.search(r"<blockquote expandable><code>(.*?)</code>", message.text, re.DOTALL).group(1)
        # The innermost on top, own code only, and the line where the exception happened in the frame that caught it
        self.assertEqual([frame.split(" in ")[1] for frame in frames.splitlines()], ["parse", "choose", "unexpected"])
        self.assertTrue(all(frame.startswith("tests/test_faults.py:") for frame in frames.splitlines()), frames)
        self.assertEqual(line["src"], frames.splitlines()[0])

    async def test_without_an_own_frame_the_last_3_frames(self):
        fault = Fault.bug(what="Unexpected exception")
        fault.__cause__ = library_error()

        await self.reporter().report(fault)

        self.assertEqual(self.block(self.send.messages[0].text)[:3],
                         ["<code>/usr/lib/python3/dist-packages/somelib.py:8 in d",
                          "/usr/lib/python3/dist-packages/somelib.py:6 in c",
                          "/usr/lib/python3/dist-packages/somelib.py:4 in b</code>"])
        [line] = self.faults()
        self.assertRegex(line["src"], r"^tests/test_faults\.py:\d+ in test_without_an_own_frame_the_last_3_frames$")

    async def test_the_media_comes_from_the_interaction_when_the_fault_has_none(self):
        reporter = self.reporter()

        async def report(fault: Fault) -> bool:
            working_on({"title": "Mickey 17", "year": 2025, "tmdbId": 696506})
            return await reporter.report(fault)

        await self.in_an_update(lambda: report(no_state_matched()))
        await self.in_an_update(lambda: report(radarr_refused()))

        mickey, dune = self.send.messages
        self.assertIn("\nMedia: Mickey 17 (2025)\n", mickey.text)
        self.assertIn("tmdb 696506", self.block(mickey.text))
        self.assertIn("\nMedia: Dune: Part Two (2024)\n", dune.text)
        self.assertEqual([line["media_title"] for line in self.faults()], ["Mickey 17", "Dune: Part Two"])

    async def test_a_bug_outside_an_interaction_gets_a_code_of_its_own(self):
        await self.reporter().report(radarr_refused())

        [line] = self.faults()
        self.assertRegex(line["interaction_id"], CODE)
        self.assertTrue(self.send.messages[0].text.endswith(f"\nCode: <code>{line['interaction_id']}</code>"))
        [sent] = self.lines("admin_message_sent")
        self.assertEqual(sent["interaction_id"], line["interaction_id"])

    async def test_a_bug_in_a_job(self):
        reporter = self.reporter()
        run = guard_job(lambda context: reporter.report(no_state_matched(), continued="skipped this movie"))

        await asyncio.create_task(run(SimpleNamespace(job=SimpleNamespace(name="check_notify_list"))))

        [message] = self.send.messages
        self.assertIn("\nJob: <code>check_notify_list</code>\n", message.text)
        self.assertIn("\nContinued: skipped this movie\n", message.text)
        self.assertNotIn("user told", message.text)
        [line] = self.faults()
        self.assertEqual(line["job"], "check_notify_list")

    async def test_a_bug_of_a_visitor_caught_outside_the_wrapper(self):
        reporter = self.reporter()

        await self.in_an_update(lambda: reporter.report(unexpected("{"), user_told=True, outside_wrapper=True),
                                user_id=323456789, first_name="Kees")

        text = self.send.messages[0].text
        self.assertIn("\nVisitor: Kees\nCaught by error_handler, outside the wrapper\n", text)
        self.assertEqual(self.block(text)[-2:], ["user_id: 323456789", "user told: yes"])


if __name__ == "__main__":
    unittest.main()
