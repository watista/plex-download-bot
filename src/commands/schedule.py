#!/usr/bin/python3

import json
import re
import time
import aiofiles
from pathlib import Path
from datetime import datetime, timezone
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

        # track whether we need to write JSON back
        changed = False

        # Iterate through notify_list
        for user_id, media_types in data.get("notify_list", {}).items():

            # Set usernames
            user_name_raw = data.get("user_id", {}).get(str(user_id), "Unknown, Unknown")
            name_parts = [p.strip() for p in user_name_raw.split(",", 1)]
            gebruiker = name_parts[0]
            username = name_parts[1]

            # Ensure keys exist
            media_types.setdefault("serie", {})
            media_types.setdefault("film", {})
            media_types.setdefault("recurring_serie", {})
            media_types.setdefault("serie_episode", {})

            # Itarate through serie and movie options
            for media_type in ["serie", "film"]:
                # Iterate through all media ID's
                for media_id, timestamp in list(media_types[media_type].items()):

                    # Get JSON data for the media ID
                    media_json = await self.sonarr.lookup_by_tmdbid(media_id) if media_type == "serie" else await self.radarr.lookup_by_tmdbid(media_id)

                    # do the required checks
                    check, media_folder, media_json = await self.check_requirements(media_json, media_id)
                    if not check:
                        continue

                    # Check if all episodes are downloaded
                    if media_type == "serie":
                        total_seasons = self.effective_season_count(media_json)

                        # Build required season tags: {"S01", "S02", ...}
                        required = {f"S{n:02d}" for n in range(1, total_seasons + 1)}

                        # Get amount of seasons
                        found, count = self.seasons_present_in_folder(media_folder)

                        # If any required season is missing, skip
                        if found < required:
                            continue

                    # Check if media_folder contains any files or subdirectories
                    if any(media_folder.iterdir()):
                        # Get Plex URL
                        media_plex_url = await self.plex.get_media_url(media_json, media_type)

                        # Sanitize title and set a var
                        sanitize_title = self.function.sanitize_text(media_json['title'])

                        # Send message
                        if not media_plex_url:
                            await self.function.send_message(f"Goed nieuws! 🎉\n\nDe {media_type} die je hebt aangevraagd, *{sanitize_title}*, staat nu online op Plęx. Veel kijkplezier! 😎", user_id, context, None, "MarkdownV2", False)
                        else:
                            await self.function.send_message(f"Goed nieuws! 🎉\n\nDe {media_type} die je hebt aangevraagd, <b>{sanitize_title}</b>, staat nu online op Plęx. Veel kijkplezier! 😎\n\n🌐 <a href='{media_plex_url}'>Bekijk {sanitize_title} in de browser</a>", user_id, context, None, "HTML", False)
                        # Write to log
                        await self.log.logger(f"*ℹ️ Notify: The {media_type} {sanitize_title} is online ℹ️*\nUser ID: {user_id}\nGebuiker: {gebruiker}\nUsername: {username}", False, "info")

                        # If it's a series: initialize recurring tracking
                        if media_type == "serie":
                            ended = bool(media_json.get("ended", False))

                            if not ended:
                                seasons_name, seasons_count = self.seasons_present_in_folder(media_folder)
                                max_seen = max(seasons_count) if seasons_count else 0

                                # Create/update recurring state for this serie
                                media_types["recurring_serie"].setdefault(str(media_id), {})
                                media_types["recurring_serie"][str(media_id)]["last_notified_season"] = max_seen
                                media_types["recurring_serie"][str(media_id)]["last_seen_season"] = max_seen
                            else:
                                media_types.get("recurring_serie", {}).pop(str(media_id), None)

                        # Delete the entry and write to data.json
                        del data["notify_list"][user_id][media_type][media_id]
                        changed = True

            # Itarate through recurring_serie options
            for media_id, state in list(media_types.get("recurring_serie", {}).items()):

                media_json = await self.sonarr.lookup_by_tmdbid(media_id)

                # do the required checks
                check, media_folder, media_json = await self.check_requirements(media_json, media_id)
                if not check:
                    continue

                seasons_name, seasons_count = self.seasons_present_in_folder(media_folder)
                if not seasons_count:
                    continue

                max_seen = max(seasons_count)

                last_notified = int(state.get("last_notified_season", 0))
                last_seen = int(state.get("last_seen_season", 0))

                # Notify if we see a new season number in files
                if max_seen > last_notified:
                    sanitize_title = self.function.sanitize_text(media_json["title"])
                    media_plex_url = await self.plex.get_media_url(media_json, "serie")

                    new_seasons = sorted(s for s in seasons_count if s > last_notified)
                    if len(new_seasons) == 1:
                        season_text = f"seizoen {new_seasons[0]}"
                    else:
                        season_text = "seizoen " + " en ".join(str(s) for s in new_seasons)

                    if not media_plex_url:
                        await self.function.send_message(f"Goed nieuws! 🎉\n\n*{season_text.capitalize()}* van *{sanitize_title}* is nu beschikbaar. Veel kijkplezier! 😎", user_id, context, None, "MarkdownV2", False)
                    else:
                        await self.function.send_message(f"Goed nieuws! 🎉\n\n<b>{season_text.capitalize()}<b/> van <b>{sanitize_title}<b/> is nu beschikbaar. Veel kijkplezier! 😎\n\n🌐 <a href='{media_plex_url}'>Bekijk {sanitize_title} in de browser</a>", user_id, context, None, "HTML", False)

                    await self.log.logger(f"*ℹ️ Notify: New season(s) for serie {sanitize_title}: {season_text} ℹ️*\nUser ID: {user_id}\nGebuiker: {gebruiker}\nUsername: {username}", False, "info")

                    state["last_notified_season"] = max_seen
                    changed = True

                # Always update last_seen_season if it increased
                if max_seen > last_seen:
                    state["last_seen_season"] = max_seen
                    changed = True

            # Iterate through serie_episode options (new episode notifications)
            for media_id, state in list(media_types.get("serie_episode", {}).items()):

                media_json = await self.sonarr.lookup_by_tmdbid(media_id)

                # do the required checks
                check, media_folder, media_json = await self.check_requirements(media_json, media_id)
                if not check:
                    continue

                episodes_found = self.episodes_present_in_folder(media_folder)
                if not episodes_found:
                    continue

                # Get highest option
                newest_found = max(episodes_found)

                # Get last notified from json
                last_notified = (state or {}).get("last", "S00E00").upper()

                # Only notify when newer episodes exist
                if newest_found <= last_notified:
                    continue

                # Gather all new episodes since last (and sort them)
                new_episodes = sorted(ep for ep in episodes_found if ep > last_notified)
                if not new_episodes:
                    continue

                sanitize_title = self.function.sanitize_text(media_json["title"])
                media_plex_url = await self.plex.get_media_url(media_json, "serie")

                # Generate episode list text
                eps_text = self.format_episode_list_nl(new_episodes)

                if not media_plex_url:
                    await self.function.send_message(f"Goed nieuws! 🎉\n\nNieuwe aflevering(en) van *{sanitize_title}* zijn nu beschikbaar:\n\n*{eps_text}*\n\nVeel kijkplezier! 😎", user_id, context, None, "MarkdownV2", False)
                else:
                    await self.function.send_message(f"Goed nieuws! 🎉\n\nNieuwe aflevering(en) van <b>{sanitize_title}</b> zijn nu beschikbaar:\n\n<b>{eps_text}</b>\n\nVeel kijkplezier! 😎\n\n🌐 <a href='{media_plex_url}'>Bekijk {sanitize_title} in de browser</a>", user_id, context, None, "HTML", False)

                await self.log.logger(f"*ℹ️ Notify: New episode(s) for serie {sanitize_title}: {eps_text} ℹ️*\n" f"User ID: {user_id}\nGebuiker: {gebruiker}\nUsername: {username}", False, "info")

                # Update last notified
                state["last"] = new_episodes[-1]
                changed = True

        # Write back once per run
        if changed:
            async with aiofiles.open(self.data_json, "w") as file:
                await file.write(json.dumps(data, indent=4))


    def effective_season_count(self, media_json: dict) -> int:
        season_count = int(media_json.get("statistics", {}).get("seasonCount", 0) or 0)

        last_aired = media_json.get("lastAired")
        if not last_aired:
            return season_count

        # lastAired is usually ISO-8601. Handle "Z" and naive timestamps.
        try:
            s = str(last_aired).strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)

            # If dt is naive, assume UTC (adjust if your API uses local time)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)

            # If lastAired is in the future, it suggests an announced season is included
            if dt > now:
                season_count = max(0, season_count - 1)

        except (ValueError, TypeError):
            # If parsing fails, just keep the original season count
            pass

        return season_count


    def seasons_present_in_folder(self, media_folder) -> set[int]:
        season_re = re.compile(r"S(\d{2})", re.IGNORECASE)
        seasons_name = set()
        seasons_count = set()
        for p in media_folder.rglob("*"):
            if not p.is_file():
                continue
            m = season_re.search(p.name)
            if m:
                seasons_name.add(f"S{int(m.group(1)):02d}")
                seasons_count.add(int(m.group(1)))
        return seasons_name, seasons_count


    def episodes_present_in_folder(self, media_folder: Path) -> set[str]:
        """
        Returns a set like {"S01E01", "S01E02", "S02E01"}
        """
        ep_re = re.compile(r"(S\d{2}E\d{2})", re.IGNORECASE)
        found = set()

        for p in media_folder.rglob("*"):
            if not p.is_file():
                continue

            m = ep_re.search(p.name)
            if m:
                found.add(m.group(1).upper())

        return found

    async def check_requirements(self, media_json, media_id):
        """
        Returns True of False if requirements are met.
        """

        # Check if data is present
        if not media_json:
            return False, False

        # Check if media_data is a list or dict
        if isinstance(media_json, list):
            media_json = media_json[0]

        # Check if path exists in the JSON
        media_folder = media_json.get("path")
        if not media_folder:
            await self.log.logger(f"❌ *No path present in JSON for media with ID {media_id}.*\nCheck the error log for more information. ❌", False, "error")
            await self.log.logger(f"Path not in the JSON. JSON: {media_json}", False, "error", False)
            return False, False

        # Check if media_folder exists
        media_folder = Path(media_folder)
        if not media_folder.is_dir():
            return False, False

        return True, media_folder, media_json


    def format_episode_list(self, episodes: list[str]) -> str:
        """
        Input:  ["S01E02", "S01E03", "S01E04"]
        Output: "Seizoen 1, Episode 2, 3 & 4"
        """

        # Convert to numbers
        parsed = []
        for ep in episodes:
            m = re.match(r"^S(\d{2})E(\d{2})$", ep.strip(), re.IGNORECASE)
            if not m:
                continue
            season = int(m.group(1))
            episode = int(m.group(2))
            parsed.append((season, episode))

        if not parsed:
            return "Nieuwe afleveringen beschikbaar."

        # Group by season
        by_season = {}
        for season, episode in parsed:
            by_season.setdefault(season, []).append(episode)

        parts = []
        for season in sorted(by_season.keys()):
            eps = sorted(set(by_season[season]))

            if len(eps) == 1:
                eps_text = f"{eps[0]}"
            elif len(eps) == 2:
                eps_text = f"{eps[0]} & {eps[1]}"
            else:
                eps_text = ", ".join(str(x) for x in eps[:-1]) + f" & {eps[-1]}"

            parts.append(f"Seizoen {season}, Episode {eps_text}")

        return " | ".join(parts)
