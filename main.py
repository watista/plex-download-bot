#!/usr/bin/python3

import os
import argparse
from dotenv import load_dotenv
from pathlib import Path
from setproctitle import setproctitle

from src.log import Log
from src.bot import Bot


def validate_env_vars() -> None:
    """Ensures required environment variables are set before execution."""
    required_vars = ["LOG_TYPE", "LOG_FOLDER", "BOT_TOKEN", "BOT_TOKEN_DEV",
                     "CHAT_ID_GROUP", "CHAT_ID_ADMIN", "RADARR_URL", "RADARR_API",
                     "SONARR_URL", "SONARR_API", "PLEX_URL", "PLEX_API",
                     "PLEX_ID", "TRANSMISSION_IP", "TRANSMISSION_PORT", "TRANSMISSION_USER",
                     "TRANSMISSION_PWD", "MOVIE_FOLDERS", "SERIE_FOLDERS"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")


def main(args, logger) -> None:
    """ Run the bot """
    Bot(args, logger)


if __name__ == '__main__':

    # Set the custom process name
    setproctitle("plex-download-bot")

    # Parse arguments
    parser = argparse.ArgumentParser(description='Plex Download Bot')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable console logging')
    parser.add_argument(
        '-e', '--env', choices=["live", "dev"], help='Environment value: live / dev', required=True)
    args = parser.parse_args()

    # Load .env file
    path = Path(
        "/root/scripts/plex-download-bot/dot-env") if args.env == "live" else Path("dot-env")
    load_dotenv(dotenv_path=path)

    # Validate environment variables
    validate_env_vars()

    # Init classes
    logger = Log(args)

    # Start the bot
    main(args, logger)
