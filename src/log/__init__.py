#!/usr/bin/python3

""" Logregels: one JSON object per line, in a file per day """

import copy
import json
import logging
import os
import sys
import traceback
from base64 import b64encode
from collections.abc import Callable
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from src.log import files


# All loggers of the bot hang under the name of its package, so the setup can tell own code from libraries
ROOT = __name__.split(".")[0]

# Folder that the paths in the field src are relative to
PROJECT_DIR = Path(__file__).resolve().parents[2]

# Fields with a fixed place. The fields of each kind of line go between msg and fault, in the order of the caller.
HEAD = ("ts", "level", "user_id", "account", "tg_name", "event", "msg")
TAIL = ("fault", "service", "interaction_id", "job", "logger", "src", "exc_type", "exc")

# The fields that say who a line is about: user_id with account for a Gebruiker, or with tg_name for a Bezoeker
PERSON = ("user_id", "account", "tg_name")

# Variables in dot-env whose values never get into a line or a Telegram message
SECRETS = ("BOT_TOKEN", "BOT_TOKEN_DEV", "RADARR_API", "SONARR_API", "PLEX_API", "TRANSMISSION_PWD")

# How a secret is quoted in a URL: by urllib by default, completely, and by transmission-rpc for its user and password
QUOTE_SAFE = ("/", "", "$-_.+!*'(),;&=")


def is_own(name: str) -> bool:
    """ True for a logger of the bot, False for a library """
    return name == ROOT or name.startswith(f"{ROOT}.")


def mask(text: str) -> str:
    """ Replaces the values of the secrets in dot-env by ***, also as they appear in a URL or in Basic auth """
    for form in _secret_forms(tuple((name, os.getenv(name)) for name in (*SECRETS, "TRANSMISSION_USER"))):
        text = text.replace(form, "***")
    return text


@lru_cache(maxsize=8)
def _secret_forms(env: tuple[tuple[str, str | None], ...]) -> tuple[str, ...]:
    """ Each secret as it is and quoted for a URL, plus the Basic auth of Transmission, the longest first in case one contains another """
    values = dict(env)
    secrets = {values[name] for name in SECRETS if values[name]}
    forms = secrets | {quote(secret, safe=safe) for secret in secrets for safe in QUOTE_SAFE}
    if values["TRANSMISSION_PWD"]:
        forms.add(_basic_auth(values["TRANSMISSION_USER"] or "", values["TRANSMISSION_PWD"]))
    return tuple(sorted(forms, key=len, reverse=True))


def _basic_auth(user: str, password: str) -> str:
    """ The Basic auth that requests sends for the user and password that transmission-rpc puts in its URL """
    credentials = f"{user}:{password}"
    try:
        return b64encode(credentials.encode("latin1")).decode("ascii")
    except UnicodeEncodeError:
        return b64encode(credentials.encode("utf-8")).decode("ascii")


def _mask_value(value):
    """ The value of a field with its secrets masked, also inside dicts and lists and in what str() makes of other objects """
    if isinstance(value, str):
        return mask(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {_mask_value(key) if isinstance(key, str) else key: _mask_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_mask_value(item) for item in value]
    return mask(str(value))


def _traceback(record: logging.LogRecord) -> str | None:
    """ The full traceback of the exception of a record, None without one (also for exc_info=True outside an except) """
    if not record.exc_info or record.exc_info[0] is None:
        return None
    return record.exc_text or "".join(traceback.format_exception(*record.exc_info)).rstrip("\n")


class OwnCodeOrWarning(logging.Filter):
    """ Lets own code through at the level of the handler, and libraries only from WARNING """

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING or is_own(record.name)


class ContextFields(logging.Filter):
    """ Gives every record the fields of the context it was written in, also a record of a library, on a copy.

    A field given as keyword wins. A person given as keywords, like the receiver of a message, replaces the
    person of the context as a whole, so a line never mixes two persons.
    """

    def __init__(self, context: Callable[[], dict]):
        super().__init__()
        self._context = context

    def filter(self, record: logging.LogRecord) -> bool | logging.LogRecord:
        context = self._context()
        if not context:
            return True
        fields = getattr(record, "fields", {})
        if any(fields.get(key) is not None for key in PERSON):
            context = {key: value for key, value in context.items() if key not in PERSON}
        with_context = copy.copy(record)
        with_context.fields = {**context, **fields}
        return with_context


class MaskSecrets(logging.Filter):
    """ Masks the secrets in every field of a record, on a copy so the record itself stays as it is """

    def filter(self, record: logging.LogRecord) -> logging.LogRecord:
        masked = copy.copy(record)
        try:
            masked.msg = mask(record.getMessage())
        except Exception:
            # Arguments that don't fit the message: keep the line with the message as it was written,
            # because a filter that raises would break the code that logs
            masked.msg = mask(str(record.msg))
        masked.args = None
        if fields := getattr(record, "fields", None):
            masked.fields = _mask_value(fields)
        if exc := _traceback(record):
            masked.exc_text = mask(exc)
        return masked


def _media_fields(media: dict) -> dict:
    """ The fields that identify a media item of Radarr or Sonarr: title, year and tmdbId, never the tvdbId """
    return {"media_title": media.get("title"), "media_year": media.get("year"), "tmdb_id": media.get("tmdbId")}


class BotLogger:
    """ Logger of a module of the bot, with the fields of a line as keywords.

    media=, a media item of Radarr or Sonarr, gives media_title, media_year and tmdb_id at once.
    """

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def debug(self, msg: str, *, exc_info=None, stacklevel: int = 1, media: dict | None = None, **fields) -> None:
        self._log(logging.DEBUG, msg, exc_info, stacklevel, media, fields)

    def info(self, msg: str, *, exc_info=None, stacklevel: int = 1, media: dict | None = None, **fields) -> None:
        self._log(logging.INFO, msg, exc_info, stacklevel, media, fields)

    def warning(self, msg: str, *, exc_info=None, stacklevel: int = 1, media: dict | None = None, **fields) -> None:
        self._log(logging.WARNING, msg, exc_info, stacklevel, media, fields)

    def error(self, msg: str, *, exc_info=None, stacklevel: int = 1, media: dict | None = None, **fields) -> None:
        self._log(logging.ERROR, msg, exc_info, stacklevel, media, fields)

    def log(self, level: int, msg: str, *, exc_info=None, stacklevel: int = 1, media: dict | None = None,
            at: traceback.FrameSummary | None = None, **fields) -> None:
        """ A line on this level. at is the frame that src names instead of the caller, like where a Fout happened. """
        self._log(level, msg, exc_info, stacklevel, media, fields, at)

    def _log(self, level: int, msg: str, exc_info, stacklevel: int, media: dict | None, fields: dict,
             at: traceback.FrameSummary | None = None) -> None:
        if not self._logger.isEnabledFor(level):
            return
        if media is not None:
            fields = {**fields, **_media_fields(media)}
        if at is None:
            # The two frames of this class are not the caller
            self._logger.log(level, msg, exc_info=exc_info, stacklevel=stacklevel + 2, extra={"fields": fields})
            return
        if isinstance(exc_info, BaseException):
            exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
        elif exc_info and not isinstance(exc_info, tuple):
            exc_info = sys.exc_info()
        self._logger.handle(self._logger.makeRecord(self._logger.name, level, at.filename, at.lineno, msg, (),
                                                    exc_info or None, func=at.name, extra={"fields": fields}))


def get_logger(name: str) -> BotLogger:
    """ The logger of a module of the bot: get_logger(__name__) """
    return BotLogger(logging.getLogger(name if is_own(name) else f"{ROOT}.{name}"))


@lru_cache(maxsize=256)
def source_path(pathname: str) -> str:
    """ The path of a file relative to the project, or as it is when it lies outside """
    try:
        return Path(pathname).resolve().relative_to(PROJECT_DIR).as_posix()
    except ValueError:
        return pathname


def is_own_file(pathname: str) -> bool:
    """ True for a file of the bot itself: in the project, and outside its virtualenv """
    path = Path(source_path(pathname))
    return not pathname.startswith("<") and not path.is_absolute() and "site-packages" not in path.parts


def line_fields(record: logging.LogRecord) -> dict:
    """ The fields of a line in their order, without the fields that have no value """

    # What the line computes itself wins from a keyword with the same name
    name = record.name.removeprefix(f"{ROOT}.") if is_own(record.name) else record.name
    values = {
        **getattr(record, "fields", {}),
        "ts": datetime.fromtimestamp(record.created, timezone.utc).astimezone().isoformat(timespec="milliseconds"),
        "level": record.levelname,
        "msg": record.getMessage(),
        "logger": name,
        "src": f"{source_path(record.pathname)}:{record.lineno} in {record.funcName}",
    }
    if exc := _traceback(record):
        values["exc_type"] = record.exc_info[0].__name__
        values["exc"] = exc

    line = {key: values[key] for key in HEAD if values.get(key) is not None}
    line.update((key, value) for key, value in values.items() if key not in HEAD + TAIL and value is not None)
    line.update((key, values[key]) for key in TAIL if values.get(key) is not None)
    return line


class JsonFormatter(logging.Formatter):
    """ A line of JSON, with UTF-8 left as it is and the separators of json.dumps """

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(line_fields(record), ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """ Text for --verbose, in the same view as the jq line in the README: ts level account event msg """

    def format(self, record: logging.LogRecord) -> str:
        line = line_fields(record)
        return f"{line['ts']} {line['level']} {line.get('account', '-')} {line.get('event', '-')} {line['msg']}"


class DayFileHandler(logging.Handler):
    """ Writes each record to the file of its own day in local time, from record.created """

    def __init__(self, folder: str, env: str, debug: bool = False):
        super().__init__()
        self.folder = folder
        self.env = env
        self.debug = debug
        self._day = None
        self._stream = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            day = datetime.fromtimestamp(record.created).date()
            if day != self._day:
                self._close_stream()
                self._stream = open(files.day_file(self.folder, self.env, day, self.debug), "a", encoding="utf-8")
                self._day = day
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def _close_stream(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
            self._day = None

    def close(self) -> None:
        with self.lock:
            self._close_stream()
        super().close()


def _configured(handler: logging.Handler, level: int, only_own_code: bool, context: Callable[[], dict],
                formatter: logging.Formatter | None = None) -> logging.Handler:
    """ The handler with its level, filters and formatter, libraries below WARNING left out if only_own_code """
    handler.setLevel(level)
    if only_own_code:
        handler.addFilter(OwnCodeOrWarning())
    handler.addFilter(ContextFields(context))
    handler.addFilter(MaskSecrets())
    handler.setFormatter(formatter or JsonFormatter())
    return handler


def setup_logging(env: str, level: str, folder: str, verbose: bool) -> None:
    """ Writes the lines of the bot and its libraries to a file per day in folder.

    The main file always gets own code from INFO and libraries from WARNING. With level DEBUG a
    debug file per day gets everything from DEBUG, also of libraries.
    """

    # The context of the Interaction a line is written in. Imported here, because src.interaction logs through this module.
    from src.interaction import context_fields

    level = level.upper()
    debug = level == "DEBUG"

    # Replace the handlers of an earlier setup
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()

    # Libraries only make records that some file needs
    root.setLevel(logging.DEBUG if debug else logging.WARNING)
    logging.getLogger(ROOT).setLevel(logging.DEBUG if debug else logging.INFO)

    Path(folder).mkdir(parents=True, exist_ok=True)
    root.addHandler(_configured(DayFileHandler(folder, env), logging.INFO, only_own_code=True,
                                context=context_fields))
    if debug:
        root.addHandler(_configured(DayFileHandler(folder, env, debug=True), logging.DEBUG, only_own_code=False,
                                    context=context_fields))
    if verbose:
        root.addHandler(_configured(logging.StreamHandler(), logging.DEBUG if debug else logging.INFO,
                                    only_own_code=True, context=context_fields, formatter=ConsoleFormatter()))

    # Python warnings become lines of the logger py.warnings
    logging.captureWarnings(True)

    # On WARNING or ERROR /log would miss the user actions
    if level not in ("INFO", "DEBUG"):
        get_logger(__name__).warning(f"LOG_TYPE={level} is not supported anymore, logging on INFO")
