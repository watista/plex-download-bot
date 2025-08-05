#!/usr/bin/python3

import json
import time
import aiofiles
from pathlib import Path
from telegram.ext import CallbackContext

from src.services.radarr import Radarr
from src.services.sonarr import Sonarr
from src.services.plex import Plex


class Schedule:

    def __init__(self, args, logger, functions):

        # Set default values
        self.log = logger
        self.function = functions
        self.radarr = Radarr(logger)
        self.sonarr = Sonarr(logger)
        self.plex = Plex(logger)

        # Set data.json file based on live/dev arg
        self.data_json = "data.json" if args.env == "live" else "data.dev.json"

    async def check_notify_list(self, context: CallbackContext) -> None:
        """ Checks if someone needs to be notified from the JSON notify list """

        # Load JSON file
        async with aiofiles.open(self.data_json, "r") as file:
            data = json.loads(await file.read())

        # Iterate through notify_list
        for user_id, media_types in data["notify_list"].items():
            # Itarate through serie and movie options
            for media_type in ["serie", "film"]:
                # Iterate through all media ID's
                for media_id, timestamp in list(media_types[media_type].items()):

                    # Get JSON data for the media ID
                    media_json = await self.sonarr.lookup_by_tmdbid(media_id) if media_type == "serie" else await self.radarr.lookup_by_tmdbid(media_id)

                    # Check if data is present
                    if not media_json:
                        continue

                    # Check if media_data is a list or dict
                    if isinstance(media_json, list):
                        media_json = media_json[0]
                        
                    media_folder = Path(media_json["path"])
                    # Check if media_folder exists
                    if media_folder.is_dir():

                        # Check if all episodes are downloaded
                        if media_type == "serie":
                            total_seasons = media_json.get(
                                "statistics", {}).get("seasonCount", 0)
                            existing_folders = len(
                                [d for d in media_folder.iterdir() if d.is_dir()])
                            if existing_folders < total_seasons:
                                continue

                        # Check if media_folder contains any files or subdirectories
                        if any(media_folder.iterdir()):
                            # Send message
                            media_plex_url = await self.plex.get_media_url(media_json, media_type)

                            # Sanitize title and set a var
                            sanitize_title = self.function.sanitize_text(
                                media_json['title'])

                            if not media_plex_url:
                                await self.function.send_message(f"Goed nieuws! 🎉\n\nDe {media_type} die je hebt aangevraagd, *{sanitize_title}*, staat nu online op Plęx. Veel kijkplezier! 😎", user_id, context, None, "MarkdownV2", False)
                            else:
                                await self.function.send_message(f"Goed nieuws! 🎉\n\nDe {media_type} die je hebt aangevraagd, *{sanitize_title}*, staat nu online op Plęx. Veel kijkplezier! 😎\n\n🌐 <a href='{media_plex_url}'>Bekijk {sanitize_title} in de browser</a>", user_id, context, None, "HTML", False)
                            # Write to log
                            await self.log.logger(f"*ℹ️ User has been notified that the {media_type} {sanitize_title} is online ℹ️*\nUser ID: {user_id}", False, "info")
                            # Delete the entry and write to data.json
                            del data["notify_list"][user_id][media_type][media_id]
                            async with aiofiles.open(self.data_json, "w") as file:
                                await file.write(json.dumps(data, indent=4))

    async def check_timestamp(self, context: CallbackContext) -> None:
        """ Checks if someone needs to be notified from the JSON notify list """

        # Load JSON file
        async with aiofiles.open(self.data_json, "r") as file:
            data = json.loads(await file.read())

        # Set notify time to 31 days in seconds
        NOTIFY_THRESHOLD = 31 * 24 * 60 * 60

        # Iterate through notify_list
        for user_id, media_types in data["notify_list"].items():
            # Itarate through serie and movie options
            for media_type in ["serie", "film"]:
                # Iterate through all media ID's
                for media_id, timestamp in list(media_types[media_type].items()):
                    waiting_time = round(time.time()) - timestamp
                    if waiting_time > NOTIFY_THRESHOLD:
                        await self.log.logger(f"*ℹ️ The {media_type} with ID {media_id} hasn't been downløaded in the past 31 days ℹ️*\nRequest by user ID: {user_id}", False, "info")
