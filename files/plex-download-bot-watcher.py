#!/usr/bin/env python3
"""Failover watcher for the Plex download bot.

Runs on the fallback host and decides when to start or stop the local bot
service based on heartbeats *pushed* by the primary host.

The direction is reversed compared to a classic poller because the primary
may not be able to accept inbound connections. The primary's bot opens an
outbound TCP connection to this watcher every few seconds (see
HEARTBEAT_TARGET_HOST / _TARGET_PORT in the bot's dot-env); the watcher
records the timestamp of each accepted connection.

Failover decisions:

* If the watcher has not seen a heartbeat for `FAIL_THRESHOLD *
  POLL_INTERVAL` seconds (default 30 s) the standby bot service is
  started in `--mode maintenance` so the Telegram bot keeps responding.
* If a fresh heartbeat arrives while the standby is active, the standby
  bot service is stopped immediately (sub-second failback). This means
  there's effectively no "success threshold" to tune — one heartbeat
  is enough to hand back control.

Environment variables (loaded from /etc/plex-download-bot-watcher.env):

    WATCHER_LISTEN_HOST          Interface to bind on        (default 0.0.0.0)
    WATCHER_LISTEN_PORT          TCP port to accept beats on (default 9876)
    WATCHER_POLL_INTERVAL        Seconds between health checks      (default 10)
    WATCHER_FAIL_THRESHOLD       Missed heartbeats before failover  (default 3)
    WATCHER_STATUS_LOG_EVERY     Emit an INFO heartbeat-summary every N checks
                                 (default 3, so every 30 s at default interval)
    WATCHER_SERVICE_NAME         Bot systemd unit on the fallback host
                                 (default plex-download-bot.service)
    WATCHER_LOG_FILE             Log file path
                                 (default /var/log/plex-download-bot-watcher.log)
"""

import asyncio
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"Invalid integer for {name}: {raw!r}, falling back to {default}", file=sys.stderr)
        return default


def setup_logging(log_file: str) -> logging.Logger:
    logger = logging.getLogger("plex-download-bot-watcher")
    logger.setLevel(logging.INFO)

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s",
                          datefmt="%d-%m-%Y %H:%M:%S")
    )
    logger.addHandler(handler)

    # Also log to stderr so `journalctl -u plex-download-bot-watcher` shows it.
    stderr = logging.StreamHandler()
    stderr.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s",
                          datefmt="%d-%m-%Y %H:%M:%S")
    )
    logger.addHandler(stderr)

    return logger


def systemctl(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["systemctl", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def service_is_active(service: str) -> bool:
    rc, _ = systemctl("is-active", "--quiet", service)
    return rc == 0


def start_service(service: str, logger: logging.Logger) -> None:
    logger.warning("Starting %s (failover to standby).", service)
    rc, out = systemctl("start", service)
    if rc != 0:
        logger.error("systemctl start %s failed (rc=%s): %s", service, rc, out)


def stop_service(service: str, logger: logging.Logger) -> None:
    logger.warning("Stopping %s (failback to primary).", service)
    rc, out = systemctl("stop", service)
    if rc != 0:
        logger.error("systemctl stop %s failed (rc=%s): %s", service, rc, out)


class WatcherState:
    """Mutable state shared between the heartbeat acceptor and the polling
    loop. Both run inside the same asyncio event loop on a single thread,
    so plain attribute access is safe — no locks needed."""

    def __init__(self, service_name: str, logger: logging.Logger):
        self.service_name = service_name
        self.logger = logger
        # `last_heartbeat_at` uses time.monotonic so it is immune to wall-clock
        # changes. Initialised to "now" so we give the primary one fail-window
        # of grace before declaring it dead at startup.
        self.last_heartbeat_at: float = time.monotonic()
        self.bot_active: bool = service_is_active(service_name)
        # Connection counter exposed in the periodic status log.
        self.beats_since_last_status: int = 0


async def handle_heartbeat(reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter,
                           state: WatcherState) -> None:
    """Called for every inbound TCP connection from the primary.

    Records the timestamp and, if the standby bot is currently running,
    stops it immediately — that gives sub-second failback as soon as the
    primary's first heartbeat arrives after an outage.
    """
    peer = writer.get_extra_info("peername")
    state.last_heartbeat_at = time.monotonic()
    state.beats_since_last_status += 1
    state.logger.debug("Heartbeat from %s.", peer)

    if state.bot_active:
        state.logger.warning(
            "Heartbeat received from %s while standby is active - handing back.",
            peer,
        )
        stop_service(state.service_name, state.logger)
        state.bot_active = service_is_active(state.service_name)

    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


async def polling_loop(state: WatcherState,
                       poll_interval: int,
                       fail_threshold: int,
                       status_log_every: int) -> None:
    """Periodically check whether the primary has gone silent."""
    fail_seconds = fail_threshold * poll_interval
    poll_counter = 0
    state.logger.info(
        "Polling loop: every %ss, take over after %ss of silence (= %s missed beats).",
        poll_interval, fail_seconds, fail_threshold,
    )

    while True:
        await asyncio.sleep(poll_interval)
        poll_counter += 1
        now = time.monotonic()
        silence_age = now - state.last_heartbeat_at

        if not state.bot_active and silence_age >= fail_seconds:
            state.logger.warning(
                "No heartbeat from primary for %.1fs (>= %ss) - taking over.",
                silence_age, fail_seconds,
            )
            start_service(state.service_name, state.logger)
            state.bot_active = service_is_active(state.service_name)

        if poll_counter % status_log_every == 0:
            state.logger.info(
                "Status: standby_bot=%s last_beat=%.1fs ago beats_in_window=%d",
                "active" if state.bot_active else "inactive",
                silence_age, state.beats_since_last_status,
            )
            state.beats_since_last_status = 0


async def main_async() -> int:
    listen_host = os.getenv("WATCHER_LISTEN_HOST", "0.0.0.0")
    listen_port = env_int("WATCHER_LISTEN_PORT", 9876)
    poll_interval = env_int("WATCHER_POLL_INTERVAL", 10)
    fail_threshold = env_int("WATCHER_FAIL_THRESHOLD", 3)
    status_log_every = max(1, env_int("WATCHER_STATUS_LOG_EVERY", 3))
    service_name = os.getenv("WATCHER_SERVICE_NAME", "plex-download-bot.service")
    log_file = os.getenv("WATCHER_LOG_FILE", "/var/log/plex-download-bot-watcher.log")

    logger = setup_logging(log_file)
    logger.info(
        "Watcher starting. listen=%s:%s poll=%ss fail_threshold=%s status_every=%s service=%s",
        listen_host, listen_port, poll_interval, fail_threshold,
        status_log_every, service_name,
    )

    state = WatcherState(service_name, logger)
    logger.info("Initial state: bot service %s is %s.",
                service_name, "active" if state.bot_active else "inactive")

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received.")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # add_signal_handler is unsupported on Windows; fall back to
            # signal.signal which is fine for the SIGTERM that systemd sends.
            signal.signal(sig, lambda *_a: stop_event.set())

    try:
        server = await asyncio.start_server(
            lambda r, w: handle_heartbeat(r, w, state),
            listen_host, listen_port,
        )
    except OSError as e:
        logger.error("Could not bind %s:%s: %s", listen_host, listen_port, e)
        return 2

    poller = asyncio.create_task(polling_loop(
        state, poll_interval, fail_threshold, status_log_every,
    ))

    async with server:
        # Serve until a stop signal arrives.
        serve_task = asyncio.create_task(server.serve_forever())
        await stop_event.wait()
        serve_task.cancel()
        try:
            await serve_task
        except (asyncio.CancelledError, Exception):
            pass

    poller.cancel()
    try:
        await poller
    except (asyncio.CancelledError, Exception):
        pass

    logger.info("Watcher stopped.")
    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
