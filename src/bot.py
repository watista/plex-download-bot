#!/usr/bin/python3

import asyncio
import os
import time
import traceback
from datetime import datetime
from typing import Optional

from src.states import VERIFY, REQUEST_ACCOUNT, REQUEST_ACCOUNT_EMAIL, REQUEST_ACCOUNT_PHONE, REQUEST_ACCOUNT_REFER, REQUEST_MOVIE, REQUEST_SERIE, VERIFY_PWD, MOVIE_OPTION, MOVIE_NOTIFY, SERIE_OPTION, SERIE_NOTIFY, MOVIE_UPGRADE, SERIE_UPGRADE, SERIE_UPGRADE_OPTION, MOVIE_UPGRADE_INFO, SERIE_UPGRADE_INFO, HELP_CHOICE, HELP_OTHER, MESSAGE_ID, MESSAGE_MESSAGE, REQUEST_AGAIN, MESSAGE_ALL_ID, AFMELDEN_OPTIE, AANMELD_OPTIE, AANMELD_CHOICE, AANMELDEN_SERIE, ADD_MOVIE, ADD_MOVIE_USER, MOVIE_UPGRADE_INFO_OTHER
from src.functions import Functions
from src.commands.privacy import Privacy
from src.commands.help import Help
from src.commands.start import Start
from src.commands.serie import Serie
from src.commands.movie import Movie
from src.commands.account import Account
from src.commands.schedule import Schedule
from src.commands.message import Message
from src.commands.subscribe import Subscribe
from src.commands.maintenance import Maintenance
from src.services.sonarr import Sonarr
from src.services.radarr import Radarr

from telegram.error import NetworkError, TimedOut, RetryAfter, Conflict
from telegram import Update, BotCommand
from telegram.ext import (
    CommandHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler,
    MessageHandler,
    Application,
    ConversationHandler,
    PicklePersistence
)


class Bot:

    def __init__(self, args, logger):

        # Set classes
        self.args = args
        self.log = logger
        self.mode = getattr(args, "mode", "normal")
        # Cooldown bookkeeping for the "two pollers detected" group-chat notice.
        # Stored as a monotonic timestamp; 0.0 means "never notified yet".
        self._conflict_notified_at: float = 0.0
        self._conflict_notify_cooldown_seconds: int = 30
        # Outbound heartbeat task handle (normal mode only). The primary may
        # not be able to accept inbound connections, so it pushes a TCP
        # heartbeat to the fallback host instead of the other way around.
        self._heartbeat_task: Optional[asyncio.Task] = None
        # Display names for the two hosts, used in group-chat notifications.
        # Defaults are intentionally generic so the project is reusable; set
        # PRIMARY_NAME / FALLBACK_NAME in dot-env to your own hostnames.
        self.primary_name: str = os.getenv("PRIMARY_NAME", "primary")
        self.fallback_name: str = os.getenv("FALLBACK_NAME", "fallback")
        self.function = Functions(logger)
        self.privacy = Privacy(logger, self.function)
        self.help = Help(logger, self.function)
        self.maintenance = Maintenance(logger, self.function)
        self.start = Start(args, logger, self.function, self.maintenance)
        self.account = Account(logger, self.function)
        self.message = Message(args, logger, self.function)
        self.allowed_users = list(map(int, os.getenv('CHAT_ID_ADMIN').split(",")))

        # Plex/Sonarr/Radarr/Transmission-dependent components are only used in
        # normal mode; on the standby (maintenance) host they would just fail.
        if self.mode == "normal":
            self.serie = Serie(args, logger, self.function)
            self.movie = Movie(args, logger, self.function)
            self.schedule = Schedule(args, logger, self.function)
            self.subscribe = Subscribe(args, logger, self.function)
            self.sonarr = Sonarr(logger)
            self.radarr = Radarr(logger)
            self.start.subscribe = self.subscribe

        # Set vars based on live/dev
        if args.env == "live":
            persistence = PicklePersistence(filepath="/root/scripts/plex-download-bot/bot_state.pkl")
            token = os.getenv('BOT_TOKEN')
        else:
            persistence = PicklePersistence(filepath="bot_state.pkl")
            token = os.getenv('BOT_TOKEN_DEV')

        # Create the Application using the new async API. post_init starts
        # the outbound heartbeat pusher so the fallback's watcher can see this
        # bot is alive; post_stop sends a group-chat notice when the fallback
        # bot shuts down (e.g. after the primary comes back).
        self.application = (
            Application.builder()
            .token(token)
            .concurrent_updates(False)
            .read_timeout(300)
            .persistence(persistence)
            .post_init(self._post_init)
            .post_stop(self._post_stop)
            .build()
        )

        # Register the appropriate conversation handler for the current mode
        if self.mode == "normal":
            self.application.add_handler(self._build_normal_conversation())
        else:
            self.application.add_handler(self._build_maintenance_conversation())

        # Add stand-alone handlers
        self.application.add_handler(
            CommandHandler("help", self.help.help_command))
        self.application.add_handler(
            CommandHandler("privacy", self.privacy.privacy_command))

        # Add error handler
        self.application.add_error_handler(self.error_handler)

        # Run the publish command function
        self.application.job_queue.run_once(lambda _: self.application.create_task(self.publish_command_list()), when=0)
        self.application.job_queue.run_once(lambda ctx: self.application.create_task(self.notify_admin_startup(ctx)), when=0)

        # Recurring jobs need Plex/Sonarr/Radarr/Transmission — only in normal mode
        if self.mode == "normal":
            self.application.job_queue.run_repeating(self.schedule.check_notify_list, interval=1800, first=0)
            self.application.job_queue.run_repeating(self.sonarr.scan_missing_media, interval=21600, first=0)
            self.application.job_queue.run_repeating(self.radarr.scan_missing_media, interval=21600, first=0)

        # Start the bot
        self.application.run_polling(
            allowed_updates=Update.ALL_TYPES, poll_interval=1, timeout=5)

    def _build_normal_conversation(self) -> ConversationHandler:
        """Full conversation handler used on the primary host."""
        return ConversationHandler(
            entry_points=[CommandHandler("start", self.start.start_msg),
                          CommandHandler("help", self.help.help_command),
                          CommandHandler("aanmelden_serie", self.start.verification),
                          CommandHandler("afmelden_serie", self.start.verification),
                          CommandHandler("aanmelden_updates", self.message.updates_subscribe),
                          CommandHandler("afmelden_updates", self.message.updates_unsubscribe),
                          CommandHandler("message", self.message.message_start, filters.User(self.allowed_users)),
                          CommandHandler("message_all", self.message.message_all, filters.User(self.allowed_users)),
                          CommandHandler("add_movie", self.message.add_movie, filters.User(self.allowed_users)),
                          MessageHandler(filters.TEXT & ~filters.COMMAND, self.start.start_msg)],
            states={
                VERIFY: [
                    CallbackQueryHandler(
                        self.start.verification, pattern="^(movie_request|serie_request|aanmelden_serie|afmelden_serie)$"),
                    CallbackQueryHandler(
                        self.message.updates_subscribe, pattern="^aanmelden_updates$"),
                    CallbackQueryHandler(
                        self.message.updates_unsubscribe, pattern="^afmelden_updates$"),
                    CallbackQueryHandler(
                        self.start.parse_request, pattern="^account_request$"),
                    CallbackQueryHandler(
                        self.help.help_command_button, pattern="^info$")
                ],
                VERIFY_PWD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.start.verify_pwd)],
                REQUEST_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.account.request_account)],
                REQUEST_ACCOUNT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.account.request_account_email)],
                REQUEST_ACCOUNT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.account.request_account_phone)],
                REQUEST_ACCOUNT_REFER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.account.request_account_refer)],
                REQUEST_MOVIE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.movie.request_media)],
                REQUEST_SERIE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.serie.request_media)],
                REQUEST_AGAIN: [CallbackQueryHandler(self.movie.request_media_again, pattern="^(yes|no)$")],
                MOVIE_OPTION: [CallbackQueryHandler(self.movie.media_option, pattern="^(0|1|2|3|4)$")],
                SERIE_OPTION: [CallbackQueryHandler(self.serie.media_option, pattern="^(0|1|2|3|4)$")],
                MOVIE_NOTIFY: [CallbackQueryHandler(self.movie.stay_notified, pattern="^(film_notify_yes|film_notify_no)$")],
                SERIE_NOTIFY: [CallbackQueryHandler(self.serie.stay_notified, pattern="^(serie_notify_yes|serie_notify_no)$")],
                MOVIE_UPGRADE: [CallbackQueryHandler(self.movie.media_upgrade, pattern="^(film_upgrade_yes|film_upgrade_no)$")],
                SERIE_UPGRADE: [CallbackQueryHandler(self.serie.media_upgrade, pattern="^(serie_upgrade_yes|serie_upgrade_no)$")],
                MOVIE_UPGRADE_INFO: [CallbackQueryHandler(self.movie.media_upgrade_info, pattern="^(quality|subs|ads|audio|other)$")],
                MOVIE_UPGRADE_INFO_OTHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.movie.media_upgrade_info_other)],
                SERIE_UPGRADE_INFO: [CallbackQueryHandler(self.serie.media_upgrade_info, pattern="^(quality|subs|ads|missing|audio|other)$")],
                SERIE_UPGRADE_OPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.serie.media_upgrade_option)],
                HELP_CHOICE: [
                    CallbackQueryHandler(
                        self.help.usage, pattern="^help_use$"),
                    CallbackQueryHandler(
                        self.help.faq, pattern="^help_faq$"),
                    CallbackQueryHandler(
                        self.help.new_account, pattern="^help_new_account$"),
                    CallbackQueryHandler(
                        self.help.quality, pattern="^help_quality$"),
                    CallbackQueryHandler(
                        self.help.other, pattern="^help_other$")
                ],
                HELP_OTHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.help.other_reply)],
                MESSAGE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.message.message_id)],
                MESSAGE_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.message.message_send)],
                MESSAGE_ALL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.message.message_all_id)],
                AFMELDEN_OPTIE: [CallbackQueryHandler(self.subscribe.afmelden_optie)],
                AANMELD_OPTIE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.subscribe.aanmeld_optie)],
                AANMELD_CHOICE: [CallbackQueryHandler(self.subscribe.aanmeld_keus)],
                AANMELDEN_SERIE: [CallbackQueryHandler(self.serie.aanmelden, pattern="^(yes|no)$")],
                ADD_MOVIE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.message.add_movie_user)],
                ADD_MOVIE_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.message.add_movie_id)],
            },
            fallbacks=[CommandHandler("stop", self.stop)],
            conversation_timeout=1800,
            per_chat=True,
            per_user=True
        )

    def _build_maintenance_conversation(self) -> ConversationHandler:
        """Slimmed conversation handler used on the fallback host.

        Plex/Sonarr/Radarr/Transmission flows are replaced with a maintenance
        notice. /start, /help, /privacy, the account request flow, algemene
        updates and the admin /message, /message_all, /add_movie commands all
        keep working because they only touch data.json and Telegram.
        """
        return ConversationHandler(
            entry_points=[CommandHandler("start", self.start.start_msg),
                          CommandHandler("help", self.help.help_command),
                          CommandHandler("aanmelden_serie", self.maintenance.media_maintenance),
                          CommandHandler("afmelden_serie", self.maintenance.media_maintenance),
                          CommandHandler("aanmelden_updates", self.message.updates_subscribe),
                          CommandHandler("afmelden_updates", self.message.updates_unsubscribe),
                          CommandHandler("message", self.message.message_start, filters.User(self.allowed_users)),
                          CommandHandler("message_all", self.message.message_all, filters.User(self.allowed_users)),
                          CommandHandler("add_movie", self.message.add_movie, filters.User(self.allowed_users)),
                          MessageHandler(filters.TEXT & ~filters.COMMAND, self.start.start_msg)],
            states={
                VERIFY: [
                    # Film / Serie / Serie-updates go through verification so
                    # blocked-user / first-time-password checks still apply,
                    # but parse_request short-circuits to a maintenance reply.
                    CallbackQueryHandler(
                        self.start.verification, pattern="^(movie_request|serie_request|aanmelden_serie|afmelden_serie)$"),
                    CallbackQueryHandler(
                        self.message.updates_subscribe, pattern="^aanmelden_updates$"),
                    CallbackQueryHandler(
                        self.message.updates_unsubscribe, pattern="^afmelden_updates$"),
                    CallbackQueryHandler(
                        self.start.parse_request, pattern="^account_request$"),
                    CallbackQueryHandler(
                        self.help.help_command_button, pattern="^info$")
                ],
                VERIFY_PWD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.start.verify_pwd)],
                REQUEST_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.account.request_account)],
                REQUEST_ACCOUNT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.account.request_account_email)],
                REQUEST_ACCOUNT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.account.request_account_phone)],
                REQUEST_ACCOUNT_REFER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.account.request_account_refer)],
                HELP_CHOICE: [
                    CallbackQueryHandler(
                        self.help.usage, pattern="^help_use$"),
                    CallbackQueryHandler(
                        self.help.faq, pattern="^help_faq$"),
                    CallbackQueryHandler(
                        self.help.new_account, pattern="^help_new_account$"),
                    CallbackQueryHandler(
                        self.help.quality, pattern="^help_quality$"),
                    CallbackQueryHandler(
                        self.help.other, pattern="^help_other$")
                ],
                HELP_OTHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.help.other_reply)],
                MESSAGE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.message.message_id)],
                MESSAGE_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.message.message_send)],
                MESSAGE_ALL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.message.message_all_id)],
                ADD_MOVIE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.message.add_movie_user)],
                ADD_MOVIE_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.message.add_movie_id)],
            },
            fallbacks=[CommandHandler("stop", self.stop)],
            conversation_timeout=1800,
            per_chat=True,
            per_user=True
        )

    async def publish_command_list(self):
        """ Create and publish command list """
        command_list = [
            BotCommand("start", "Commando om de bot te starten"),
            BotCommand("aanmelden_serie", "Aanmelden op nieuwe serie afleveringen"),
            BotCommand("afmelden_serie", "Afmelden op nieuwe serie afleveringen"),
            BotCommand("aanmelden_updates", "Aanmelden op algemene updates"),
            BotCommand("afmelden_updates", "Afmelden op algemene updates"),
            BotCommand("help", "Krijg alle informatie te zien van deze bot"),
            BotCommand("privacy", "Toont de privacy policy van de bot")
        ]
        await self.application.bot.set_my_commands(command_list)

    async def notify_admin_startup(self, context: CallbackContext) -> None:
        """Notify group chat(s) that the bot started."""
        raw_group_id = os.getenv("CHAT_ID_GROUP")
        if not raw_group_id:
            return
        try:
            group_id = int(raw_group_id)
        except ValueError:
            await self.log.logger(f"Invalid CHAT_ID_GROUP value: {raw_group_id}", False, "warning", False)
            return

        started_at = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        env_label = "live" if self.args.env == "live" else "dev"
        if self.mode == "maintenance":
            msg = f"⚠️ Standby bot gestart op {self.fallback_name} ({env_label}, maintenance) om {started_at}."
        else:
            msg = f"✅ Bot gestart ({env_label}) om {started_at}."

        try:
            await self.function.send_message(msg, group_id, context, None, "MarkdownV2", False)
        except Exception as e:
            await self.log.logger(f"Failed to notify group startup to {group_id}: {e}", False, "warning", False)

    async def _post_init(self, application: Application) -> None:
        """PTB hook that runs after init but before polling begins.

        On the primary (normal mode) this starts the outbound heartbeat
        pusher so the fallback's watcher can tell the bot process is alive.
        The fallback (maintenance mode) does not push.
        """
        if self.mode == "normal":
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _post_stop(self, application: Application) -> None:
        """PTB hook that runs after polling stops.

        Both modes announce the shutdown to the group chat. In addition:
        * On the primary the goodbye packet is sent to the fallback's
          watcher *first* so failover starts immediately, even if the
          subsequent Telegram send is slow.
        * On the fallback only the announcement is sent; the watcher already
          knows what it's doing (it's the one that stopped this process).
        """
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            self._heartbeat_task = None

        # Fast path first: get the fallback going before we spend time on
        # the Telegram round-trip.
        if self.mode == "normal":
            await self._send_goodbye_to_fallback()

        stopped_at = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        env_label = "live" if self.args.env == "live" else "dev"
        if self.mode == "normal":
            msg = (
                f"⚠️ Bot op {self.primary_name} gestopt ({env_label}) om {stopped_at}. "
                f"{self.fallback_name} neemt het tijdelijk over."
            )
        else:
            msg = (
                f"ℹ️ Standby bot op {self.fallback_name} gestopt ({env_label}) om {stopped_at}. "
                f"{self.primary_name} is weer online en heeft het overgenomen."
            )

        await self._send_group_message(application, msg)

    async def _send_group_message(self, application: Application, msg: str) -> None:
        """Send a one-off MarkdownV2 message to CHAT_ID_GROUP; swallow errors.

        Used by the shutdown hook; safe to call from contexts where a failure
        must not propagate (e.g. PTB's post_stop, which would otherwise be
        able to delay or break systemd's shutdown sequence).
        """
        raw_group_id = os.getenv("CHAT_ID_GROUP")
        if not raw_group_id:
            return
        try:
            group_id = int(raw_group_id)
        except ValueError:
            await self.log.logger(f"Invalid CHAT_ID_GROUP value: {raw_group_id}", False, "warning", False)
            return

        try:
            await application.bot.send_message(
                chat_id=group_id,
                text=self.log.escape_markdown(msg),
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
        except Exception as e:
            await self.log.logger(f"Failed to send shutdown notice to {group_id}: {e}", False, "warning", False)

    async def _heartbeat_loop(self) -> None:
        """Push a TCP heartbeat to the fallback host every HEARTBEAT_INTERVAL
        seconds while this (primary) bot is running.

        The primary may be unable to accept inbound connections, so the
        direction is reversed: the primary opens a connection to the
        fallback's watcher (listening on HEARTBEAT_TARGET_HOST:
        HEARTBEAT_TARGET_PORT) and closes it again. That single connect is
        enough — the fallback records the timestamp and treats prolonged
        silence as a primary outage.

        Misconfiguration is logged on the first failure and otherwise quietly
        retried; a broken heartbeat must not crash the bot.
        """
        target_host = os.getenv("HEARTBEAT_TARGET_HOST")
        if not target_host:
            await self.log.logger(
                "HEARTBEAT_TARGET_HOST not set; outbound heartbeat disabled.",
                False, "warning", False,
            )
            return

        try:
            target_port = int(os.getenv("HEARTBEAT_TARGET_PORT", "9876"))
        except ValueError as e:
            await self.log.logger(
                f"Invalid HEARTBEAT_TARGET_PORT: {e}; outbound heartbeat disabled.",
                False, "warning", False,
            )
            return

        try:
            interval = max(1, int(os.getenv("HEARTBEAT_INTERVAL", "10")))
        except ValueError:
            interval = 10

        await self.log.logger(
            f"Heartbeat pusher started; sending to {target_host}:{target_port} every {interval}s.",
            False, "info", False,
        )

        consecutive_failures = 0
        while True:
            try:
                _reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(target_host, target_port),
                    timeout=5,
                )
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                if consecutive_failures:
                    await self.log.logger(
                        f"Heartbeat to {target_host}:{target_port} recovered after {consecutive_failures} failures.",
                        False, "info", False,
                    )
                consecutive_failures = 0
            except asyncio.CancelledError:
                raise
            except (OSError, asyncio.TimeoutError) as e:
                consecutive_failures += 1
                # Only log the first failure and then every 30th to avoid log
                # flooding when the fallback host is genuinely unreachable.
                if consecutive_failures == 1 or consecutive_failures % 30 == 0:
                    await self.log.logger(
                        f"Heartbeat to {target_host}:{target_port} failed ({consecutive_failures}x): {e}",
                        False, "warning", False,
                    )

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise

    async def _send_goodbye_to_fallback(self) -> None:
        """Best-effort 'I'm shutting down' notice to the fallback's watcher.

        Opens a TCP connection to HEARTBEAT_TARGET_HOST:HEARTBEAT_TARGET_PORT,
        writes a single ``BYE\\n`` line and closes. The watcher distinguishes
        a goodbye from a regular heartbeat by the presence of this payload
        and reacts by starting the fallback bot immediately, instead of
        waiting for the silence threshold.

        Any error is logged and swallowed: a missed goodbye is not a fault
        condition because the silence-based takeover still covers it.
        """
        target_host = os.getenv("HEARTBEAT_TARGET_HOST")
        if not target_host:
            return
        try:
            target_port = int(os.getenv("HEARTBEAT_TARGET_PORT", "9876"))
        except ValueError:
            return

        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(target_host, target_port),
                timeout=3,
            )
            writer.write(b"BYE\n")
            try:
                await asyncio.wait_for(writer.drain(), timeout=2)
            except asyncio.TimeoutError:
                pass
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=2)
            except (asyncio.TimeoutError, Exception):
                pass
            await self.log.logger(
                f"Goodbye signal sent to {target_host}:{target_port}.",
                False, "info", False,
            )
        except Exception as e:
            await self.log.logger(
                f"Failed to send goodbye to {target_host}:{target_port}: {e}",
                False, "warning", False,
            )

    async def error_handler(self, update: Update, context: CallbackContext) -> None:
        """ Function for unexpted errors """

        # the actual exception object
        err = context.error

        # --- handle specific errors first ---
        if isinstance(err, RetryAfter):
            await self.log.logger(f"Rate limited by Telegram. Retry after {err.retry_after} seconds.", False, "warning", False)
            return

        if isinstance(err, TimedOut):
            await self.log.logger("Telegram request timed out.", False, "warning", False)
            return

        if isinstance(err, NetworkError):
            await self.log.logger(f"Network error while calling Telegram: {err}", False, "warning", False)
            return

        if isinstance(err, Conflict):
            await self.log.logger("Telegram Conflict: Another bot instance is running.", False, "warning", False)
            # Only the standby surfaces this to the group chat — both instances
            # will see the Conflict (Telegram alternates winners), so notifying
            # from one side keeps the chat from getting two messages per cycle.
            if self.mode == "maintenance":
                await self._notify_conflict_to_group(context)
            return

        # --- fallback: log full traceback for unknown errors ---
        error_message = "".join(traceback.format_exception(None, err, err.__traceback__))
        await self.log.logger(f"Unexpected error happened with Telegram dispatcher\n{error_message}", False, "error")

    async def _notify_conflict_to_group(self, context: CallbackContext) -> None:
        """Send a rate-limited heads-up to the group when both bot instances
        are polling at the same time. Called from the maintenance bot only."""
        now = time.monotonic()
        if now - self._conflict_notified_at < self._conflict_notify_cooldown_seconds:
            return
        self._conflict_notified_at = now

        raw_group_id = os.getenv("CHAT_ID_GROUP")
        if not raw_group_id:
            return
        try:
            group_id = int(raw_group_id)
        except ValueError:
            await self.log.logger(f"Invalid CHAT_ID_GROUP value: {raw_group_id}", False, "warning", False)
            return

        detected_at = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        env_label = "live" if self.args.env == "live" else "dev"
        msg = (
            f"⚠️ *Conflict gedetecteerd* ({env_label}, {detected_at})\n\n"
            f"De standby bot op {self.fallback_name} kreeg een Telegram Conflict, wat betekent "
            f"dat er nog een andere instance van de bot draait (waarschijnlijk {self.primary_name}). "
            f"Controleer welke server actief moet blijven en stop de andere handmatig."
        )

        try:
            await self.function.send_message(msg, group_id, context, None, "MarkdownV2", False)
        except Exception as e:
            await self.log.logger(f"Failed to send Conflict notice to group {group_id}: {e}", False, "warning", False)

    async def stop(self, update: Update, context: CallbackContext) -> None:
        """ Cancel command """
        await self.function.send_message(f"Oke gestopt. Stuur /start om opnieuw te beginnen.", update, context)
        return ConversationHandler.END
