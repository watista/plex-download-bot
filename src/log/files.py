#!/usr/bin/python3

""" Names of the day files, shared by the handler that writes them and the reader of /log """

import re
from datetime import date
from pathlib import Path


def prefix(env: str) -> str:
    """ Live (also in maintenance mode) and dev write to their own files """
    return "plex-download-bot" if env == "live" else "dev-plex-download-bot"


def day_file(folder: str, env: str, day: date, debug: bool = False) -> Path:
    """ The file of this day, or its debug file """
    suffix = "-debug" if debug else ""
    return Path(folder) / f"{prefix(env)}-{day.isoformat()}{suffix}.jsonl"


def day_files(folder: str, env: str) -> list[tuple[date, Path]]:
    """ The main files in the folder by their day, oldest first, without the debug files and old .log files """
    pattern = re.compile(rf"{re.escape(prefix(env))}-(\d{{4}}-\d{{2}}-\d{{2}})\.jsonl")
    found = []
    for path in Path(folder).glob("*.jsonl"):
        if match := pattern.fullmatch(path.name):
            found.append((date.fromisoformat(match.group(1)), path))
    return sorted(found)
