#!/usr/bin/python3

import base64
import inspect
import io
import json
import logging
import os
import tempfile
import time
import unittest
import warnings
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import httpx
import requests
import transmission_rpc
from transmission_rpc.error import TransmissionAuthError

from src.bot import Bot
from src.log import get_logger, mask, setup_logging
from src.log.legacy import Log
from src.telegram_out import TelegramOut


# Secrets as they could be in dot-env
SECRETS = {
    "BOT_TOKEN": "111111:live-token-AAAA",
    "BOT_TOKEN_DEV": "222222:dev-token-BBBB",
    "RADARR_API": "radarr0123456789abcdef",
    "SONARR_API": "sonarr0123456789abcdef",
    "PLEX_API": "plexTokenXyZ",
    "TRANSMISSION_PWD": "hunter2-transmission",
}

def unauthorized(adapter, request, **kwargs) -> requests.Response:
    """ What Transmission answers to a request with a wrong password """
    response = requests.Response()
    response.status_code = 401
    response.request = request
    response.url = request.url
    response._content = b"<h1>401: Unauthorized</h1>"
    return response


# The main file and the debug file of dev on 3 November 2026, the day most tests write on
MAIN = "dev-plex-download-bot-2026-11-03.jsonl"
DEBUG = "dev-plex-download-bot-2026-11-03-debug.jsonl"


class LogFolder:
    """ A temporary log folder with the secrets of dot-env, in Dutch local time """

    def setUp(self):

        # A temporary LOG_FOLDER
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

        # The secrets from dot-env and Dutch local time, which changes clock on 29 March and 25 October 2026
        env = patch.dict(os.environ, {"TZ": "Europe/Amsterdam", **SECRETS})
        env.start()
        time.tzset()
        self.addCleanup(time.tzset)
        self.addCleanup(env.stop)
        self.addCleanup(self.reset_logging)

    def reset_logging(self):
        """ Closes the handlers of setup_logging, so the next test starts clean """
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
            handler.close()
        logging.captureWarnings(False)

    def at(self, moment: str):
        """ Freezes the clock of the log records at this ISO 8601 moment """
        return patch("time.time", return_value=datetime.fromisoformat(moment).timestamp())

    def raw(self, name: str) -> str:
        """ The text of a file in the log folder, empty if there is no such file """
        path = self.folder / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def read(self, name: str) -> list[dict]:
        """ The lines of a file in the log folder """
        return [json.loads(line) for line in self.raw(name).splitlines()]


class LogLinesTest(LogFolder, unittest.TestCase):
    """ Logregels through setup_logging and get_logger, read back from a temporary log folder """

    def test_fields_in_their_order_without_empty_ones(self):
        setup_logging("dev", "INFO", str(self.folder), False)

        # The fields with a fixed place go there, whatever order the caller gives them in
        with self.at("2026-11-03T14:05:12.345+01:00"):
            get_logger("src.commands.media").info(
                "searched 'dune' for movie: 7 results",
                event="search_term", query="dune", media_type="movie", results=7, skipped=0,
                tg_name=None, account="wouter", interaction_id="k7p2qx", user_id=123456789)

        [line] = self.read(MAIN)
        self.assertEqual(list(line), ["ts", "level", "user_id", "account", "event", "msg", "query", "media_type",
                                      "results", "skipped", "interaction_id", "logger", "src"])
        self.assertEqual(line["ts"], "2026-11-03T14:05:12.345+01:00")
        self.assertEqual(line["level"], "INFO")
        self.assertEqual(line["msg"], "searched 'dune' for movie: 7 results")
        self.assertEqual(line["skipped"], 0)

        # /log searches with a substring, so the separators are those of json.dumps
        raw = self.raw(MAIN)
        self.assertIn('"user_id": 123456789, "account": "wouter"', raw)

    def test_logger_and_src_are_those_of_the_caller(self):
        setup_logging("dev", "INFO", str(self.folder), False)

        with self.at("2026-11-03T14:05:12+01:00"):
            line_number = inspect.currentframe().f_lineno + 1
            get_logger("src.commands.media").info("searched 'dune' for movie: 7 results")

        [line] = self.read(MAIN)
        self.assertEqual(line["logger"], "commands.media")
        self.assertEqual(line["src"], f"tests/test_log.py:{line_number} in test_logger_and_src_are_those_of_the_caller")

    def test_keywords_do_not_replace_the_fields_of_the_line_itself(self):
        setup_logging("dev", "INFO", str(self.folder), False)

        with self.at("2026-11-03T14:05:12+01:00"):
            get_logger("src.commands.media").info("searched 'dune'", ts="yesterday", level="X", logger="fake", src="mine")

        [line] = self.read(MAIN)
        self.assertEqual((line["ts"], line["level"], line["msg"], line["logger"]),
                         ("2026-11-03T14:05:12.000+01:00", "INFO", "searched 'dune'", "commands.media"))
        self.assertTrue(line["src"].startswith("tests/test_log.py:"), line["src"])

    def test_media_gives_its_title_year_and_tmdb_id(self):
        setup_logging("dev", "INFO", str(self.folder), False)

        with self.at("2026-11-03T14:05:12+01:00"):
            get_logger("src.commands.media").info(
                "requested Dune (2021)", event="media_request", outcome="download_started",
                media={"title": "Dune", "year": 2021, "tmdbId": 438631, "tvdbId": 1, "overview": "Paul Atreides"})

        [line] = self.read(MAIN)
        self.assertEqual(list(line), ["ts", "level", "event", "msg", "outcome", "media_title", "media_year", "tmdb_id",
                                      "logger", "src"])
        self.assertEqual((line["media_title"], line["media_year"], line["tmdb_id"]), ("Dune", 2021, 438631))

    def test_exc_info_without_an_exception(self):
        setup_logging("dev", "INFO", str(self.folder), False)

        with self.at("2026-11-03T14:05:12+01:00"):
            get_logger("src.bot").error("nothing went wrong after all", exc_info=True)

        [line] = self.read(MAIN)
        self.assertEqual(line["msg"], "nothing went wrong after all")
        self.assertNotIn("exc_type", line)
        self.assertNotIn("exc", line)

    def test_utf8_stays_literal(self):
        setup_logging("dev", "INFO", str(self.folder), False)

        with self.at("2026-11-03T14:05:12+01:00"):
            get_logger("src.commands.media").info("searched 'Amélie' for movie: 1 result 🎬", query="Amélie")

        raw = self.raw(MAIN)
        self.assertIn('"msg": "searched \'Amélie\' for movie: 1 result 🎬", "query": "Amélie"', raw)

    def test_secrets_are_masked_in_every_field(self):
        setup_logging("dev", "INFO", str(self.folder), False)

        with self.at("2026-11-03T14:05:12+01:00"):
            try:
                raise ConnectionError(f"http://user:{SECRETS['TRANSMISSION_PWD']}@transmission:9091 refused")
            except ConnectionError:
                get_logger("src.services.arr").error(
                    f"GET https://api.telegram.org/bot{SECRETS['BOT_TOKEN_DEV']}/getMe failed",
                    exc_info=True,
                    url=f"https://radarr/api/v3/movie?apikey={SECRETS['RADARR_API']}",
                    response={"token": SECRETS["PLEX_API"], "keys": [SECRETS["SONARR_API"]]},
                    path=Path(f"/tmp/{SECRETS['BOT_TOKEN']}"))

        raw = self.raw(MAIN)
        for name, secret in SECRETS.items():
            self.assertNotIn(secret, raw, name)
        [line] = self.read(MAIN)
        self.assertEqual(line["msg"], "GET https://api.telegram.org/bot***/getMe failed")
        self.assertEqual(line["url"], "https://radarr/api/v3/movie?apikey=***")
        self.assertEqual(line["response"], {"token": "***", "keys": ["***"]})
        self.assertEqual(line["path"], "/tmp/***")
        self.assertEqual(line["exc_type"], "ConnectionError")
        self.assertIn("ConnectionError: http://user:***@transmission:9091 refused", line["exc"])

    def test_info_of_a_library_only_in_the_debug_file(self):
        setup_logging("dev", "DEBUG", str(self.folder), False)

        with self.at("2026-11-03T14:05:12+01:00"):
            get_logger("src.services.arr").debug("radarr GET response", event="http_call")
            get_logger("src.bot").info("bot started", event="bot_started")
            logging.getLogger("telegram.ext.Application").info("Application started")
            logging.getLogger("apscheduler.scheduler").warning("Run time of job was missed by 0:00:02")

        main = self.read(MAIN)
        self.assertEqual([line["msg"] for line in main], ["bot started", "Run time of job was missed by 0:00:02"])
        debug = self.read(DEBUG)
        self.assertEqual([line["msg"] for line in debug], ["radarr GET response", "bot started", "Application started",
                                                          "Run time of job was missed by 0:00:02"])
        self.assertEqual([line["logger"] for line in debug], ["services.arr", "bot", "telegram.ext.Application",
                                                             "apscheduler.scheduler"])

    def test_no_debug_file_on_info(self):
        setup_logging("dev", "INFO", str(self.folder), False)

        with self.at("2026-11-03T14:05:12+01:00"):
            get_logger("src.services.arr").debug("radarr GET response", event="http_call")
            get_logger("src.bot").info("bot started", event="bot_started")

        self.assertEqual([path.name for path in self.folder.iterdir()], [MAIN])
        self.assertEqual([line["msg"] for line in self.read(MAIN)], ["bot started"])

    def test_an_old_log_type_logs_on_info(self):

        # LOG_TYPE only knows INFO and DEBUG now, on WARNING /log would miss the user actions
        with self.at("2026-11-03T14:05:12+01:00"):
            setup_logging("dev", "WARNING", str(self.folder), False)
            get_logger("src.bot").info("bot started", event="bot_started")

        main = self.read(MAIN)
        self.assertEqual([(line["level"], line["msg"]) for line in main], [
            ("WARNING", "LOG_TYPE=WARNING is not supported anymore, logging on INFO"),
            ("INFO", "bot started"),
        ])
        self.assertFalse((self.folder / DEBUG).exists())

    def test_no_bot_token_in_the_urls_of_httpx(self):
        setup_logging("dev", "DEBUG", str(self.folder), False)

        # PTB puts the bot token in the URL, and httpx logs every URL on INFO
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
        with self.at("2026-11-03T14:05:12+01:00"), httpx.Client(transport=transport) as client:
            client.post(f"https://api.telegram.org/bot{SECRETS['BOT_TOKEN_DEV']}/getUpdates")

        self.assertNotIn("getUpdates", self.raw(MAIN))
        debug = self.raw(DEBUG)
        self.assertIn("https://api.telegram.org/bot***/getUpdates", debug)
        self.assertNotIn(SECRETS["BOT_TOKEN_DEV"], debug)

    def test_mask(self):
        self.assertEqual(mask(f"/bot{SECRETS['BOT_TOKEN']}/sendMessage to {SECRETS['PLEX_API']}"), "/bot***/sendMessage to ***")
        self.assertEqual(mask(f"token={quote(SECRETS['BOT_TOKEN'], safe='')}"), "token=***")

    def test_the_transmission_password_is_also_masked_in_its_url_and_basic_auth(self):
        setup_logging("dev", "DEBUG", str(self.folder), False)

        # transmission-rpc puts its own logger on ERROR. On DEBUG it logs its URL with the password quoted
        # in it, and after a 401 the request headers with Basic auth.
        transmission = logging.getLogger("transmission-rpc")
        self.addCleanup(transmission.setLevel, transmission.level)
        transmission.setLevel(logging.NOTSET)

        password = "p@ss/wörd:1"
        with self.at("2026-11-03T14:05:12+01:00"), \
                patch.dict(os.environ, {"TRANSMISSION_USER": "wouter", "TRANSMISSION_PWD": password}), \
                patch("requests.adapters.HTTPAdapter.send", unauthorized):
            with self.assertRaises(TransmissionAuthError):
                transmission_rpc.Client(host="transmission", username="wouter", password=password)

        debug = self.raw(DEBUG)
        self.assertIn("http://wouter:***@transmission:9091/transmission/rpc", debug)
        self.assertIn("'Authorization': 'Basic ***'", debug)
        for form in (password, "p%40ss%2Fw%C3%B6rd%3A1", base64.b64encode("wouter:p@ss/wörd:1".encode("latin1")).decode()):
            self.assertNotIn(form, debug)

    def test_console_with_verbose(self):

        # Own code from LOG_TYPE, libraries from WARNING, as text like the jq line in the README
        with patch("sys.stderr", new_callable=io.StringIO) as console:
            setup_logging("dev", "DEBUG", str(self.folder), True)
            with self.at("2026-11-03T14:05:12.345+01:00"):
                get_logger("src.commands.media").info("searched 'dune' for movie: 7 results", event="search_term",
                                                      account="wouter", query="dune")
                get_logger("src.services.arr").debug(f"GET /api/v3/movie?apikey={SECRETS['RADARR_API']}")
                logging.getLogger("telegram.ext.Application").info("Application started")
                logging.getLogger("apscheduler.scheduler").warning("Run time of job was missed by 0:00:02")

        self.assertEqual(console.getvalue().splitlines(), [
            "2026-11-03T14:05:12.345+01:00 INFO wouter search_term searched 'dune' for movie: 7 results",
            "2026-11-03T14:05:12.345+01:00 DEBUG - - GET /api/v3/movie?apikey=***",
            "2026-11-03T14:05:12.345+01:00 WARNING - - Run time of job was missed by 0:00:02",
        ])

    def test_no_console_without_verbose(self):
        with patch("sys.stderr", new_callable=io.StringIO) as console:
            setup_logging("dev", "INFO", str(self.folder), False)
            get_logger("src.bot").info("bot started", event="bot_started")

        self.assertEqual(console.getvalue(), "")

    def test_python_warnings_become_lines_but_not_the_one_about_per_message(self):
        setup_logging("dev", "INFO", str(self.folder), False)

        # Bot with only what its conversation handlers need
        bot = Bot.__new__(Bot)
        for name in ("start", "help", "message", "account", "movie", "serie", "subscribe", "maintenance"):
            setattr(bot, name, MagicMock())
        bot.allowed_users = [1]

        with self.at("2026-11-03T14:05:12+01:00"), warnings.catch_warnings():
            warnings.simplefilter("always")
            bot._build_normal_conversation()
            bot._build_maintenance_conversation()
            warnings.warn("something new", UserWarning)

        [line] = self.read(MAIN)
        self.assertEqual((line["level"], line["logger"]), ("WARNING", "py.warnings"))
        self.assertIn("UserWarning: something new", line["msg"])

    def test_existing_log_files_stay_as_they_are(self):
        old = self.folder / "dev-wouter-thuisserver-bot-11-01-2026.log"
        old.write_text("01-11-2026 10:00:00 - INFO - root: User started bot with /start\n")
        os.utime(old, (1_700_000_000, 1_700_000_000))

        setup_logging("dev", "DEBUG", str(self.folder), False)
        with self.at("2026-11-03T14:05:12+01:00"):
            get_logger("src.bot").info("bot started", event="bot_started")

        self.assertEqual(old.read_text(), "01-11-2026 10:00:00 - INFO - root: User started bot with /start\n")
        self.assertEqual(old.stat().st_mtime, 1_700_000_000)

    def write_at(self, *moments: str) -> None:
        """ Writes a line at each moment, with the moment as msg """
        log = get_logger("src.bot")
        for moment in moments:
            with self.at(moment):
                log.info(moment)

    def lines_per_day(self) -> dict[str, list[str]]:
        """ The ts of the lines in each main file, by the date in the name of the file """
        return {path.name.removeprefix("dev-plex-download-bot-").removesuffix(".jsonl"): [line["ts"] for line in self.read(path.name)]
                for path in sorted(self.folder.iterdir())}

    def test_a_new_file_at_midnight_local_time(self):
        setup_logging("dev", "INFO", str(self.folder), False)

        self.write_at("2026-11-03T23:59:59.999+01:00", "2026-11-04T00:00:00.000+01:00")

        self.assertEqual(self.lines_per_day(), {
            "2026-11-03": ["2026-11-03T23:59:59.999+01:00"],
            "2026-11-04": ["2026-11-04T00:00:00.000+01:00"],
        })

    def test_a_new_file_at_midnight_after_winter_time_starts(self):
        setup_logging("dev", "INFO", str(self.folder), False)

        # On 25 October 2026 the clock goes back from 03:00 to 02:00, so that day has 25 hours
        self.write_at("2026-10-24T23:59:59.999+02:00", "2026-10-25T00:00:00.000+02:00", "2026-10-25T02:30:00.000+02:00",
                      "2026-10-25T02:30:00.000+01:00", "2026-10-25T23:59:59.999+01:00", "2026-10-26T00:00:00.000+01:00")

        self.assertEqual(self.lines_per_day(), {
            "2026-10-24": ["2026-10-24T23:59:59.999+02:00"],
            "2026-10-25": ["2026-10-25T00:00:00.000+02:00", "2026-10-25T02:30:00.000+02:00",
                           "2026-10-25T02:30:00.000+01:00", "2026-10-25T23:59:59.999+01:00"],
            "2026-10-26": ["2026-10-26T00:00:00.000+01:00"],
        })

    def test_a_new_file_at_midnight_after_summer_time_starts(self):
        setup_logging("dev", "INFO", str(self.folder), False)

        # On 29 March 2026 the clock goes forward from 02:00 to 03:00, so that day has 23 hours
        self.write_at("2026-03-28T23:59:59.999+01:00", "2026-03-29T01:59:59.999+01:00", "2026-03-29T03:00:00.000+02:00",
                      "2026-03-29T23:59:59.999+02:00", "2026-03-30T00:00:00.000+02:00")

        self.assertEqual(self.lines_per_day(), {
            "2026-03-28": ["2026-03-28T23:59:59.999+01:00"],
            "2026-03-29": ["2026-03-29T01:59:59.999+01:00", "2026-03-29T03:00:00.000+02:00", "2026-03-29T23:59:59.999+02:00"],
            "2026-03-30": ["2026-03-30T00:00:00.000+02:00"],
        })


class StartStopTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ The start and stop of the bot replace those of PTB in the main file """

    async def test_bot_started_and_bot_stopped(self):
        setup_logging("dev", "INFO", str(self.folder), False)

        # The standby bot, which has no heartbeat, and a fake Telegram
        bot = Bot.__new__(Bot)
        bot.args = SimpleNamespace(env="dev")
        bot.mode = "maintenance"
        bot._heartbeat_task = None
        bot.primary_name, bot.fallback_name = "primary", "fallback"
        bot.log = MagicMock()
        application = MagicMock()
        application.bot.send_message = AsyncMock()
        bot.telegram = TelegramOut(application.bot, "-1", AsyncMock(return_value=None))

        with self.at("2026-11-03T14:05:12+01:00"):
            await bot._post_init(application)
            await bot._post_stop(application)

        main = self.read(MAIN)
        self.assertEqual([(line["level"], line["event"], line["msg"]) for line in main], [
            ("INFO", "bot_started", "bot started: dev, maintenance mode"),
            ("INFO", "admin_message_sent", "admin message sent: bot stopped"),
            ("INFO", "bot_stopped", "bot stopped: dev, maintenance mode"),
        ])
        self.assertEqual(application.bot.send_message.await_args.kwargs["chat_id"], "-1")


class OldLogClassTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ The old calls of Log keep working on top of the new logging, until the issues after 01 replace them """

    def old_log(self) -> Log:
        """ Log with a fake Telegram bot """
        log = Log(SimpleNamespace(env="dev", verbose=False))
        log.bot = MagicMock()
        log.bot.send_message = AsyncMock()
        return log

    async def test_logger_writes_the_text_without_markdown_for_the_caller(self):
        setup_logging("dev", "INFO", str(self.folder), False)
        log = self.old_log()

        with self.at("2026-11-03T14:05:12+01:00"):
            line_number = inspect.currentframe().f_lineno + 1
            await log.logger("*ℹ️ Notify: New episode(s) for serie Shōgun ℹ️*\nUser ID: 1", False, "info", chat_id=1)

        [line] = self.read(MAIN)
        self.assertEqual(line["level"], "INFO")
        self.assertEqual(line["msg"], "*ℹ️ Notify: New episode(s) for serie Shōgun ℹ️*\nUser ID: 1")
        self.assertEqual(line["logger"], __name__)
        self.assertEqual(line["src"], f"tests/test_log.py:{line_number} in test_logger_writes_the_text_without_markdown_for_the_caller")

        # Telegram still gets MarkdownV2
        self.assertEqual(log.bot.send_message.await_args.kwargs["text"],
                         "*ℹ️ Notify: New episode\\(s\\) for serie Shōgun ℹ️*\nUser ID: 1")

    async def test_debug_call_writes_an_http_call(self):
        setup_logging("dev", "DEBUG", str(self.folder), False)
        log = self.old_log()

        with self.at("2026-11-03T14:05:12+01:00"), patch.dict(os.environ, {"LOG_MAX_BODY": "20"}):
            line_number = inspect.currentframe().f_lineno + 1
            await log.debug_call("movie", "GET response", url="https://radarr/api/v3/movie/lookup?term=dune",
                                 status=200, duration=0.3204, response=[{"title": "Dune", "year": 2021}])

        self.assertEqual(self.read(MAIN), [])
        [line] = self.read(DEBUG)
        self.assertEqual(line, {
            "ts": "2026-11-03T14:05:12.000+01:00",
            "level": "DEBUG",
            "event": "http_call",
            "msg": "radarr GET response",
            "method": "GET",
            "url": "https://radarr/api/v3/movie/lookup?term=dune",
            "http_status": 200,
            "duration_ms": 320,
            "response": '[{"title": "Dune", "... [truncated, 33 chars total]',
            "service": "radarr",
            "logger": __name__,
            "src": f"tests/test_log.py:{line_number} in test_debug_call_writes_an_http_call",
        })


if __name__ == "__main__":
    unittest.main()
