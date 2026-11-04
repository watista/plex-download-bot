#!/usr/bin/python3

""" Loglezer: the lines of a person or of one Code in the day files, from new to old, for /log """

import asyncio
import json
import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from itertools import islice
from pathlib import Path
from typing import BinaryIO

from src.log import ROOT, files


# The folder of the package of the bot, whose modules the own loggers are named after
PACKAGE = Path(__file__).resolve().parents[1]

# The bytes read at a time, going back from the end of a file
BLOCK = 64 * 1024

# The lines found per step in a thread: the files are read lazily, so a page that is full reads no further
BATCH = 100


@dataclass(frozen=True, order=True)
class Position:
    """ Where a line starts: the day of its file, and its byte offset in that file """
    day: date
    offset: int


@dataclass(frozen=True)
class Query:
    """ What to look for: the lines of a person, by the user IDs and the account name, or the lines of one Code.

    The account name is found in any case, so it also finds a name that is no longer in the user list.
    """
    user_ids: frozenset[int] = frozenset()
    account: str | None = None
    code: str | None = None


@dataclass(frozen=True)
class Found:
    """ A line that a search found, with where it starts """
    position: Position
    line: dict


async def search(folder: str, env: str, query: Query, before: Position | None = None,
                 after: Position | None = None) -> AsyncIterator[Found]:
    """ The lines that match the query, from new to old: only those before `before` and after `after`.

    It reads the main files of env in folder, without the debug files and the old .log files, binary and back
    from the end in blocks. Each line first gets a substring check, and only then json.loads. All of it runs
    in asyncio.to_thread. A half last line, which the bot is still writing, is skipped. The lines of a Code are
    of one Interaction, so the search stops at the first older file without them.
    """
    matcher = _Matcher(query)
    code_found = False
    for day, path in reversed(await asyncio.to_thread(files.day_files, folder, env)):
        if before is not None and day > before.day:
            continue
        if after is not None and day < after.day:
            return
        end = before.offset if before is not None and day == before.day else None
        floor = after.offset if after is not None and day == after.day else -1
        found_in_file = False
        lines = _found_in_file(path, day, end, floor, matcher)
        try:
            while batch := await asyncio.to_thread(lambda: list(islice(lines, BATCH))):
                found_in_file = True
                for found in batch:
                    yield found
        finally:
            lines.close()
        if query.code is not None:
            if found_in_file:
                code_found = True
            elif code_found:
                return


def from_library(line: dict) -> bool:
    """ True for a line of a library, False for one of the bot itself: by its logger, as the setup tells them apart.

    A line of a library never has an event or a fault. A logger of the bot hangs under the name of its package, which
    the field logger leaves out, so it names a module of the bot. Any other logger is a library.
    """
    if line.get("event") is not None or line.get("fault") is not None:
        return False
    logger = line.get("logger")
    return not (isinstance(logger, str) and _is_own_logger(logger))


@lru_cache(maxsize=256)
def _is_own_logger(name: str) -> bool:
    """ Whether the logger of a line is one of the bot: the package itself, the script that starts the bot, or a
    module or package in it """
    if name in (ROOT, "__main__"):
        return True
    parts = name.split(".")
    if not all(part.isidentifier() for part in parts):
        return False
    path = PACKAGE.joinpath(*parts)
    return path.with_suffix(".py").is_file() or path.is_dir()


class _Matcher:
    """ Whether a line is one the query looks for: a cheap check on the bytes first, the fields after json.loads """

    def __init__(self, query: Query):
        self._user_ids = query.user_ids
        self._account = query.account.casefold() if query.account is not None else None
        self._code = query.code

        # The fields as the JSON of a line has them, with the separators of json.dumps. "user_id": 12 is also in
        # "user_id": 123, so the fields decide.
        self._user_id_needles = [f'"user_id": {user_id}'.encode() for user_id in query.user_ids]
        self._account_needle = None if query.account is None else \
            f'"account": {json.dumps(query.account, ensure_ascii=False)}'.casefold()
        self._ascii_account_needle = self._account_needle.encode() \
            if self._account_needle is not None and self._account_needle.isascii() else None
        self._code_needle = None if query.code is None else f'"interaction_id": {json.dumps(query.code)}'.encode()

    def might_match(self, raw: bytes) -> bool:
        """ The cheap check on the bytes of a line: False when it cannot be one of the query """
        if any(needle in raw for needle in self._user_id_needles):
            return True
        if self._code_needle is not None and self._code_needle in raw:
            return True
        if self._account_needle is None:
            return False
        # The account in any case. Most lines are ASCII, whose casefold is its lower case, so the bytes do;
        # the others only as text.
        if raw.isascii():
            return self._ascii_account_needle is not None and self._ascii_account_needle in raw.lower()
        return self._account_needle in raw.decode("utf-8", "replace").casefold()

    def matches(self, line: dict) -> bool:
        """ Whether the fields of a line are those of the query """
        user_id, account = line.get("user_id"), line.get("account")
        return ((isinstance(user_id, int) and user_id in self._user_ids)
                or (self._account is not None and isinstance(account, str) and account.casefold() == self._account)
                or (self._code is not None and line.get("interaction_id") == self._code))


def _found_in_file(path: Path, day: date, end: int | None, floor: int, matcher: _Matcher) -> Iterator[Found]:
    """ The lines of one file that match, from new to old: those that start after floor and before end, the end of
    the file when None """
    with path.open("rb") as file:
        if end is None:
            end = file.seek(0, os.SEEK_END)
        for offset, raw in _lines_backward(file, end):
            if offset <= floor:
                return
            if not matcher.might_match(raw):
                continue
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if isinstance(line, dict) and matcher.matches(line):
                yield Found(Position(day, offset), line)


def _lines_backward(file: BinaryIO, end: int) -> Iterator[tuple[int, bytes]]:
    """ The complete lines before end, from new to old, each with the offset where it starts.

    Every line the bot wrote ends with a newline, so what comes after the last newline is a half line that the bot
    is still writing: it is skipped. The buffer always ends at the end of a line that is not given yet.
    """
    buffer = b""
    buffer_start = end
    at_line_end = False
    while buffer_start > 0:
        start = max(0, buffer_start - BLOCK)
        file.seek(start)
        buffer = file.read(buffer_start - start) + buffer
        buffer_start = start

        if not at_line_end:
            newline = buffer.rfind(b"\n")
            if newline == -1:
                # All of it is part of the half line
                buffer = b""
                continue
            buffer = buffer[:newline + 1]
            at_line_end = True

        # A line is complete when it starts after a newline in the buffer, or at the start of the file
        first = 0 if buffer_start == 0 else buffer.find(b"\n") + 1
        lines = buffer[first:].split(b"\n")[:-1]
        offsets = []
        offset = buffer_start + first
        for raw in lines:
            offsets.append(offset)
            offset += len(raw) + 1
        for offset, raw in reversed(list(zip(offsets, lines))):
            if raw.strip():
                yield offset, raw
        buffer = buffer[:first]
