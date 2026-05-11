#!/usr/bin/env python3
"""Failover watcher for the Plex download bot.

Runs on the standby host (`shared`) and probes the primary host (`AIVD`)
with a TCP connect every `POLL_INTERVAL` seconds.

* After `FAIL_THRESHOLD` consecutive failed probes the standby bot service
  is started so the Telegram bot keeps responding (in `--mode maintenance`).
* After `SUCCESS_THRESHOLD` consecutive successful probes (i.e. the primary
  is back) the standby bot service is stopped, returning control to the
  primary.

The bot service on shared must be installed but *not* enabled at boot — the
watcher manages it. Only one of the two hosts should ever be polling the
Telegram API at a time; this watcher is what guarantees that.

Environment variables (loaded from /etc/plex-download-bot-watcher.env):

    WATCHER_TARGET_HOST          Hostname or IP of the primary (required)
    WATCHER_TARGET_PORT          TCP port to probe                  (default 22)
    WATCHER_POLL_INTERVAL        Seconds between probes             (default 10)
    WATCHER_FAIL_THRESHOLD       Consecutive fails to fail over     (default 3)
    WATCHER_SUCCESS_THRESHOLD    Consecutive ok'es to fail back     (default 3)
    WATCHER_PROBE_TIMEOUT        TCP connect timeout in seconds     (default 3)
    WATCHER_SERVICE_NAME         Bot systemd unit on shared
                                 (default plex-download-bot.service)
    WATCHER_LOG_FILE             Log file path
                                 (default /var/log/plex-download-bot-watcher.log)
"""

import logging
import logging.handlers
import os
import signal
import socket
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


def tcp_probe(host: str, port: int, timeout: float) -> bool:
    """Return True when a TCP connect to host:port completes within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


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


_running = True


def _handle_signal(signum, _frame):  # noqa: ANN001 - signal handler signature
    global _running
    _running = False


def main() -> int:
    target_host = os.getenv("WATCHER_TARGET_HOST")
    if not target_host:
        print("WATCHER_TARGET_HOST is required.", file=sys.stderr)
        return 2

    target_port = env_int("WATCHER_TARGET_PORT", 80)
    poll_interval = env_int("WATCHER_POLL_INTERVAL", 10)
    fail_threshold = env_int("WATCHER_FAIL_THRESHOLD", 3)
    success_threshold = env_int("WATCHER_SUCCESS_THRESHOLD", 3)
    probe_timeout = env_int("WATCHER_PROBE_TIMEOUT", 3)
    service_name = os.getenv("WATCHER_SERVICE_NAME", "plex-download-bot.service")
    log_file = os.getenv("WATCHER_LOG_FILE", "/var/log/plex-download-bot-watcher.log")

    logger = setup_logging(log_file)
    logger.info(
        "Watcher starting. target=%s:%s interval=%ss fail=%s success=%s service=%s",
        target_host, target_port, poll_interval, fail_threshold, success_threshold, service_name,
    )

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    consecutive_fails = 0
    consecutive_successes = 0

    # Reconcile our model with reality at startup: if the bot is already
    # running, assume we've already failed over and only need success_threshold
    # successes to stop it again.
    bot_active = service_is_active(service_name)
    logger.info("Initial state: bot service %s is %s.",
                service_name, "active" if bot_active else "inactive")

    while _running:
        ok = tcp_probe(target_host, target_port, probe_timeout)

        if ok:
            consecutive_successes += 1
            consecutive_fails = 0
            logger.debug("Probe ok (%d consecutive).", consecutive_successes)
        else:
            consecutive_fails += 1
            consecutive_successes = 0
            logger.debug("Probe failed (%d consecutive).", consecutive_fails)

        if not bot_active and consecutive_fails >= fail_threshold:
            logger.warning(
                "Primary %s:%s unreachable for %d consecutive probes - taking over.",
                target_host, target_port, consecutive_fails,
            )
            start_service(service_name, logger)
            bot_active = service_is_active(service_name)
            consecutive_fails = 0  # reset so we don't try to start again next tick

        elif bot_active and consecutive_successes >= success_threshold:
            logger.warning(
                "Primary %s:%s reachable for %d consecutive probes - handing back.",
                target_host, target_port, consecutive_successes,
            )
            stop_service(service_name, logger)
            bot_active = service_is_active(service_name)
            consecutive_successes = 0

        # Allow signals to interrupt the sleep promptly.
        for _ in range(poll_interval):
            if not _running:
                break
            time.sleep(1)

    logger.info("Watcher stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
