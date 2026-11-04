#!/usr/bin/python3

import html
import json
import re
import time
import aiofiles
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from telegram.ext import CallbackContext

from src.commands.media import title_and_year
from src.faults import Fault, FaultKind, service_name
from src.interaction import account_in, tally, working_on
from src.log import get_logger
from src.services.radarr import Radarr
from src.services.sonarr import Sonarr
from src.services.plex import Plex
from src.services.transmission import TransmissionService


log = get_logger(__name__)

# The counts of a run of check_notify_list for guard_job, each with how its line job_finished says it: items checked
# and Gebruikersberichten delivered (counted by send_user_message), and only as fields the Gebruikersberichten that
# did not arrive (counted by send_user_message too) and the items skipped by an Inrichtingsfout
NOTIFY_COUNTS = {
    "items": "{n} item{s} checked",
    "sent": "{n} message{s} sent",
    "not_delivered": None,
    "skipped": None,
}


@dataclass
class ItemCheck:
    """ What check_notify_list found for one item of the notify list, for its line notify_check.

    media is the movie or series in Radarr or Sonarr, or only its tmdbId when the run skipped the item before Radarr
    or Sonarr gave it. folder is its folder, None when there is none to look in. outcome is what the check came to:
    no_data, no_folder, seasons_missing (with the seasons missing), empty_folder, nothing_new or sent.
    """
    media: dict
    folder: Path | None
    outcome: str | None = None
    missing: list[str] | None = None


class Schedule:

    def __init__(self, args, logger, functions, telegram, faults):

        # Set default values
        self.log = logger
        self.function = functions
        self.telegram = telegram
        self.faults = faults
        self.radarr = Radarr(faults)
        self.sonarr = Sonarr(faults)
        self.plex = Plex(faults)
        self.transmission = TransmissionService(faults)

        # Whether Transmission answered at the previous run of check_transmission: None before the first run after
        # a start, when the bot does not know
        self._last_transmission_up: bool | None = None

        # Set data.json file based on live/dev arg
        self.data_json = "data.json" if args.env == "live" else "data.dev.json"

    async def check_transmission(self, context: CallbackContext) -> None:
        """ Checks that Transmission answers. A Fault ends the run, and goes to the wrapper of the job.

        When Transmission answers while it did not at the previous run, Sonarr and Radarr start the searches for their
        missing media: what they found meanwhile could not go to Transmission. After a start the bot does not know
        whether Transmission answered before, so the first run starts nothing.
        """
        try:
            await self.transmission.check()
        except Fault:
            self._last_transmission_up = False
            raise

        back = self._last_transmission_up is False
        self._last_transmission_up = True
        if back:
            log.info("Transmission is back: starting the missing searches in Sonarr and Radarr",
                     event="transmission_back")
            await self.sonarr.scan_missing_media()
            await self.radarr.scan_missing_media()

    async def check_notify_list(self, context: CallbackContext) -> None:
        """ Checks if someone needs to be notified from the JSON notify list.

        Every item checked counts for the run, and gets a line notify_check with its outcome. An Inrichtingsfout of one
        item is reported, and the run skips that item. A Storing or a Bug ends the run.
        """

        # Load JSON file
        async with aiofiles.open(self.data_json, "r") as file:
            data = json.loads(await file.read())

        # track whether we need to write JSON back
        changed = False

        # The messages to the Beheerder about the users notified in this run. They go once data.json is
        # written, so a failure to send one never makes a user get the same Gebruikersbericht again.
        notified = []

        try:
            # Iterate through notify_list
            for user_id, media_types in data.get("notify_list", {}).items():

                # Set usernames
                user_name_raw = data.get("user_id", {}).get(str(user_id), "Unknown, Unknown")
                name_parts = [p.strip() for p in user_name_raw.split(",", 1)]
                gebruiker = name_parts[0]
                username = name_parts[1]

                # Who gets the Gebruikersberichten, for the lines notify_check
                receiver = {"user_id": int(user_id), "account": account_in(data, user_id)}

                # Ensure keys exist
                media_types.setdefault("serie", {})
                media_types.setdefault("film", {})
                media_types.setdefault("recurring_serie", {})
                media_types.setdefault("serie_episode", {})

                # Itarate through serie and movie options
                for media_type in ["serie", "film"]:
                    client = self.sonarr if media_type == "serie" else self.radarr

                    # Iterate through all media ID's
                    for media_id, timestamp in list(media_types[media_type].items()):
                        async with self.checking("online", receiver, client, media_id) as check:
                            if check.folder is None:
                                continue
                            media_json, media_folder = check.media, check.folder

                            # Check if all episodes are downloaded
                            if media_type == "serie":
                                total_seasons = self.effective_season_count(media_json)

                                # Build required season tags: {"S01", "S02", ...}
                                required = {f"S{n:02d}" for n in range(1, total_seasons + 1)}

                                # Get amount of seasons
                                found, count = self.seasons_present_in_folder(media_folder)

                                # If any required season is missing, skip
                                if found < required:
                                    check.outcome, check.missing = "seasons_missing", sorted(required - found)
                                    continue

                            # Skip a media_folder without any files or subdirectories
                            if not any(media_folder.iterdir()):
                                check.outcome = "empty_folder"
                                continue

                            # Get Plex URL
                            media_plex_url = await self.plex.link(media_json, media_type)

                            # The title in HTML for the user, and without * and _ for the MarkdownV2 of the Beheerder
                            html_title = html.escape(media_json['title'])
                            sanitize_title = self.function.sanitize_text(media_json['title'])

                            # Send message
                            delivery = await self.telegram.send_user_message(
                                user_id, "online",
                                f"Goed nieuws! 🎉\n\nDe {media_type} die je hebt aangevraagd, <b>{html_title}</b>, staat nu online op Plęx. Veel kijkplezier! 😎{self.plex_link(html_title, media_plex_url)}",
                                media_json)
                            check.outcome = "sent"
                            if delivery.delivered:
                                notified.append((f"*ℹ️ User notified: The {media_type} {sanitize_title} ({media_id}) is online ℹ️*\nUser ID: {user_id}\nGebuiker: {gebruiker}\nUsername: {username}", "user notified: online"))

                            # If it's a series: initialize recurring tracking
                            if media_type == "serie":
                                ended = bool(media_json.get("ended", False))

                                if not ended:
                                    # Only do this if serie_episode tracking exists; otherwise skip
                                    if "serie_episode" not in media_types:
                                        continue

                                    seasons_name, seasons_count = self.seasons_present_in_folder(media_folder)
                                    max_seen = max(seasons_count) if seasons_count else 0

                                    # Initialize serie_episode tracking so we don't spam old episodes.
                                    latest_ep = self.newest_episode_in_folder(media_folder)
                                    media_types["serie_episode"].setdefault(str(media_id), {})
                                    media_types["serie_episode"][str(media_id)]["started"] = True
                                    media_types["serie_episode"][str(media_id)]["last"] = latest_ep or "S00E00"

                                    # Create/update recurring state for this serie
                                    media_types["recurring_serie"].setdefault(str(media_id), {})
                                    media_types["recurring_serie"][str(media_id)]["last_notified_season"] = max_seen
                                    media_types["recurring_serie"][str(media_id)]["last_seen_season"] = max_seen
                                else:
                                    media_types.get("recurring_serie", {}).pop(str(media_id), None)
                                    media_types.get("serie_episode", {}).pop(str(media_id), None)

                            # Delete the entry and write to data.json
                            del data["notify_list"][user_id][media_type][media_id]
                            changed = True

                # Itarate through recurring_serie options
                for media_id, state in list(media_types.get("recurring_serie", {}).items()):
                    async with self.checking("new_season", receiver, self.sonarr, media_id) as check:
                        if check.folder is None:
                            continue
                        media_json, media_folder = check.media, check.folder

                        seasons_name, seasons_count = self.seasons_present_in_folder(media_folder)
                        if not seasons_count:
                            check.outcome = "empty_folder"
                            continue

                        max_seen = max(seasons_count)

                        last_notified = int(state.get("last_notified_season", 0))
                        last_seen = int(state.get("last_seen_season", 0))

                        # Notify if we see a new season number in files
                        check.outcome = "nothing_new"
                        if max_seen > last_notified:
                            html_title = html.escape(media_json["title"])
                            sanitize_title = self.function.sanitize_text(media_json["title"])
                            media_plex_url = await self.plex.link(media_json, "serie")

                            new_seasons = sorted(s for s in seasons_count if s > last_notified)
                            if len(new_seasons) == 1:
                                season_text = f"seizoen {new_seasons[0]}"
                            else:
                                season_text = "seizoen " + " en ".join(str(s) for s in new_seasons)

                            delivery = await self.telegram.send_user_message(
                                user_id, "new_season",
                                f"Goed nieuws! 🎉\n\n<b>{season_text.capitalize()}</b> van <b>{html_title}</b> is nu beschikbaar. Veel kijkplezier! 😎{self.plex_link(html_title, media_plex_url)}",
                                media_json)
                            check.outcome = "sent"
                            if delivery.delivered:
                                notified.append((f"*ℹ️ Notify: New season(s) for serie {sanitize_title}: {season_text} ℹ️*\nUser ID: {user_id}\nGebuiker: {gebruiker}\nUsername: {username}", "user notified: new_season"))

                            state["last_notified_season"] = max_seen
                            changed = True

                        # Always update last_seen_season if it increased
                        if max_seen > last_seen:
                            state["last_seen_season"] = max_seen
                            changed = True

                # Iterate through serie_episode options (new episode notifications)
                for media_id, state in list(media_types.get("serie_episode", {}).items()):
                    async with self.checking("new_episodes", receiver, self.sonarr, media_id) as check:
                        if check.folder is None:
                            continue
                        media_json, media_folder = check.media, check.folder

                        # Only start notifying after started=True: until then the series is not online, and there
                        # is nothing new to tell
                        if not bool((state or {}).get("started", False)):
                            check.outcome = "nothing_new"
                            continue

                        episodes_found = self.function.episodes_present_in_folder(media_folder)
                        if not episodes_found:
                            check.outcome = "empty_folder"
                            continue

                        # Get highest option
                        newest_found = max(episodes_found)

                        # Get last notified from json
                        last_notified = (state or {}).get("last", "S00E00").upper()

                        # Only notify when newer episodes exist
                        if newest_found <= last_notified:
                            check.outcome = "nothing_new"
                            continue

                        # Gather all new episodes since last (and sort them)
                        new_episodes = sorted(ep for ep in episodes_found if ep > last_notified)
                        if not new_episodes:
                            check.outcome = "nothing_new"
                            continue

                        html_title = html.escape(media_json["title"])
                        sanitize_title = self.function.sanitize_text(media_json["title"])
                        media_plex_url = await self.plex.link(media_json, "serie")

                        # Generate episode list text
                        eps_text = self.format_episode_list(new_episodes)

                        delivery = await self.telegram.send_user_message(
                            user_id, "new_episodes",
                            f"Goed nieuws! 🎉\n\nNieuwe aflevering(en) van <b>{html_title}</b> zijn nu beschikbaar:\n\n<b>{html.escape(eps_text)}</b>\n\nVeel kijkplezier! 😎{self.plex_link(html_title, media_plex_url)}",
                            media_json)
                        check.outcome = "sent"
                        if delivery.delivered:
                            notified.append((f"*ℹ️ Notify: New episode(s) for serie {sanitize_title}: {eps_text} ℹ️*\n" f"User ID: {user_id}\nGebuiker: {gebruiker}\nUsername: {username}", "user notified: new_episodes"))

                        # Update last notified
                        state["last"] = new_episodes[-1]
                        changed = True
        finally:
            # Write back once per run, also after a Fout that ended it: who got a Gebruikersbericht in this run must
            # not get it again in the next
            if changed:
                async with aiofiles.open(self.data_json, "w") as file:
                    await file.write(json.dumps(data, indent=4))

        for text, about in notified:
            await self.telegram.send_admin_message(text, about)


    @staticmethod
    def plex_link(html_title: str, media_plex_url: str | None) -> str:
        """ The HTML link to the media in Plex for the end of a Gebruikersbericht, empty without a URL """
        if not media_plex_url:
            return ""
        return f"\n\n🌐 <a href=\"{html.escape(media_plex_url)}\">Bekijk {html_title} in de browser</a>"


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


    def seasons_present_in_folder(self, media_folder: Path) -> tuple[set[str], set[int]]:
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


    def newest_episode_in_folder(self, media_folder: Path) -> str | None:
        episodes = self.function.episodes_present_in_folder(media_folder)
        if not episodes:
            return None
        return max(episodes)


    @asynccontextmanager
    async def checking(self, kind: str, receiver: dict, client: Radarr | Sonarr,
                       media_id: str) -> AsyncIterator[ItemCheck]:
        """ Checks one item of the notify list, for a Gebruikersbericht of this kind to the receiver (its user_id and
        account): async with self.checking(...) as check.

        First the movie or series and its folder (start_check). Without a folder the item has its outcome then, and
        the body skips it: if check.folder is None: continue. Otherwise the body sets the outcome.

        After the body the item counts as checked, and gets its line notify_check on DEBUG. The receiver is on that
        line as keywords, not in the context: a Fout during the item has no user fields, and stays out of
        /log <person>. A Fout that ends the run ends it without that line.
        """
        check = await self.start_check(client, media_id)
        yield check

        tally("items")
        outcome = check.outcome.replace("_", " ") + (f" {', '.join(check.missing)}" if check.missing else "")
        log.debug(f"checked {title_and_year(check.media)} for {receiver['account'] or receiver['user_id']} ({kind}): "
                  f"{outcome}", event="notify_check", kind=kind, outcome=check.outcome, missing=check.missing,
                  media=check.media, **receiver)
        # Done with it: a Fout after it is not about it
        working_on(None)

    async def start_check(self, client: Radarr | Sonarr, media_id: str) -> ItemCheck:
        """ The start of the check of an item: the movie or series in Radarr or Sonarr, and its folder.

        The Interaction is working on the item from the moment Radarr or Sonarr gives it. A folder that is not there
        gives the outcome no_folder: nothing is downloaded yet. An item that Radarr or Sonarr does not find, or that
        has no path there, is an Inrichtingsfout of that item: reported, and the item is skipped with the outcome
        no_data. Any other Fout falls through and ends the run, also an Inrichtingsfout like a wrong key, which every
        next item would run into as well.
        """
        path_check, name = f"{client.media_type}_path", service_name(client.service)
        try:
            media_json = await client.lookup_by_tmdbid(media_id)
            working_on(media_json)
            if not media_json.get("path"):
                raise Fault.setup(service=client.service, what=f"{media_json.get('title')} has no path in {name}",
                                  check=path_check, item=media_id, media=media_json)
        except Fault as fault:
            if fault.kind != FaultKind.SETUP or str(fault.item) != str(media_id):
                raise
            await self.faults.report(fault, continued="skipped this item")
            tally("skipped")
            tmdb_id = int(media_id) if str(media_id).isdigit() else media_id
            return ItemCheck(fault.media or {"tmdbId": tmdb_id}, None, "no_data")
        await self.faults.fixed(client.service, path_check, media_id,
                                msg=f"{media_json.get('title')} now has a path in {name}")

        media_folder = Path(media_json["path"])
        if not media_folder.is_dir():
            return ItemCheck(media_json, None, "no_folder")
        return ItemCheck(media_json, media_folder)


    def format_episode_list(self, episodes) -> str:
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
