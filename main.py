#!/usr/bin/python3

from dotenv import load_dotenv
import argparse
import asyncio

from src.log import Log
from src.bot import Bot
from src.plex import Plex
from src.arr import Arr


if __name__ == '__main__':

    # Parse arguments
    parser = argparse.ArgumentParser(description='Plex Download Bot')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable console logging')
    parser.add_argument('-e', '--env', help='Environment value: live / dev')
    args = parser.parse_args()

    # Env var is live/dev
    if args.env not in ["live", "dev"]:
        parser.error("Environment value --env/-e required.\nPossible values: live / dev")

    # Load .env file
    path = "/root/scripts/plex-download-bot/dot-env" if args.env == "live" else "dot-env"
    load_dotenv(dotenv_path=path)

    # Init classes
    logger = Log(args)
    plex = Plex(logger)
    arr = Arr(logger)

    # Start the bot
    Bot(logger, plex, arr)

    # # Init bot
    # async def main() -> None:
    #     Bot(logger, plex, arr)

    # asyncio.run(main())
