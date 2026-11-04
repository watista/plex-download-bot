[GPLv3 License](https://opensource.org/licenses/)
Python Version

# Plex download Telegram bot

This projects uses Plex, Sonarr, Radarr and Transmission to automate download requests for your Plex server.

## Getting started

### Environment variables and tokens

Copy the `dot-env.template` to the root folder with the name `dot-env` and fill in the variables

```
BOT_TOKEN: The token of your Telegram Bot
RADARR_URL: Your Radarr url (including port)
RADARR_API: Your Radarr API key
SONARR_URL: Your Sonarr url (including port)
SONARR_API: Your Sonarr API key
PLEX_URL: Your Plex url (including port)
PLEX_API: Your Plex API key
PLEX_ID: Your Plex server ID
CHAT_ID_GROUP: The Telegram Chat ID
CHAT_ID_ADMIN: User telegram ID
LOG_TYPE: INFO or DEBUG. The main log always has INFO and up; DEBUG adds a debug file per day
with everything, see Logs below. Any other value logs on INFO, with a warning at every start
LOG_FOLDER: Folder to write logs to
TRANSMISSION_IP: The external IP of your Transmission instance
TRANSMISSION_PORT: Transmission port
TRANSMISSION_USER: Transmission user
TRANSMISSION_PWD: Transmission password
MOVIE_FOLDERS: One or multiple paths of the movie folders attached to your Plex instance
SERIE_FOLDERS: One or multiple paths of the serie folders attached to your Plex instance
```

### Create JSON files

```
cd ~./plex-download-bot/
tee data.json data.dev.json < data.json.template
tee stats.json stats.dev.json < stats.json.template
```

In the `data.json` file you'll find 4 dict's, only the first one called `users` has to be filled manually. The key can be a name or username corresponding with the value, which should be a password which users can use to login with the bot.
The rest of the dicts are used and filled by the script. This is also the case for `stats.json`.
The `*.dev.json` file are the same, the only difference is that the `dev` file is used when the argument `--env dev` is given.

## Setup the environment

Create the python environment and install required packages

```
cd ~./plex-download-bot/
python3.10 -m venv env
source env/bin/activate
pip install -r requirements.txt
deactivate
```

## Create systemd service

Create `/etc/systemd/system/plex-download-bot.service` from `~/plex-download-bot/files/plex-download-bot.service`

Enable and start the service

```
sudo systemctl daemon-reload
sudo systemctl enable plex-download-bot.service
sudo systemctl start plex-download-bot.service
```

## Usage

```
# Run the script
~./plex-download-bot/env/bin/python3 ~./plex-download-bot/main.py
# or
source ~./plex-download-bot/env/bin/activate
python3 ~./plex-download-bot/main.py

# Arguments
./main.py -h                            # Show help
./main.py -v                            # Show console output
./main.py --verbose                     # Show console output
./main.py -e dev/live                   # Set env to dev or live
./main.py --env dev/live                # Set env to dev or live
./main.py -m normal/maintenance         # Run mode (default: normal)
./main.py --mode normal/maintenance     # Run mode (default: normal)

```

## Logs

The bot writes one file per calendar day in local time to `LOG_FOLDER`, as JSON Lines: one JSON
object per line, in UTF-8.

- `plex-download-bot-YYYY-MM-DD.jsonl` on live (also in maintenance mode), and
`dev-plex-download-bot-YYYY-MM-DD.jsonl` on dev. This main file always has the bot's own lines from
INFO and the lines of libraries from WARNING.
- With `LOG_TYPE=DEBUG` there is a second file per day, `…-YYYY-MM-DD-debug.jsonl`, with everything
from DEBUG, libraries included. It gets big fast: switch DEBUG on temporarily.
- Nothing is renamed or removed. Old `.log` files stay as they are.
- The bot tokens, API keys and the Transmission password from `dot-env` are replaced by `***` in
every line, also in the lines of libraries.
- `--verbose` also shows the lines on the console: own lines from `LOG_TYPE`, libraries from WARNING.

Read a file as text with `jq`:

```
jq -r '"\(.ts) \(.level) \(.account // "-") \(.event // "-") \(.msg)"' log/plex-download-bot-2026-11-03.jsonl
```

Follow today's file over SSH. This stops following at midnight, when the bot starts the next file:

```
tail -F log/plex-download-bot-$(date +%F).jsonl | jq -r '"\(.ts) \(.level) \(.account // "-") \(.event // "-") \(.msg)"'
```

`jq -r .exc` shows a traceback over multiple lines again.

In Telegram, the admin (`CHAT_ID_ADMIN`) can read the logs of the host the bot runs on with
`/log <account name | user ID | code>`, in the private chat with the bot: the latest lines of a person, or
all lines of the interaction with the code of an error message. "⬅️ Earlier" and "Later ➡️" browse
back and forth. Without an argument, `/log` explains itself.

## High availability (primary + fallback)

The bot is deployed on two hosts so users keep getting responses when the
primary server is down:

- **Primary** runs the bot in `--mode normal` and serves all features.
- **Fallback** runs the bot in `--mode maintenance`, started only by a
watcher when the primary is unreachable. In maintenance mode Plex, Sonarr,
Radarr and Transmission are not used — any film/serie/serie-updates request
is answered with a "we're in maintenance" message. The admin `/message`,
`/message_all`, `/add_movie` and `/log` commands keep working, as do `/start` (with
the maintenance reply for media options), `/help`, `/privacy`, the new
account flow, and `/aanmelden_updates` / `/afmelden_updates`.

Set the `PRIMARY_NAME` and `FALLBACK_NAME` variables in each host's
`dot-env` to the hostnames you actually use; they are interpolated into
the group-chat notifications the bot sends on failover/failback/conflict.

Telegram allows only one active `getUpdates` poller per bot token, so
**only one of the two hosts may run the bot at any time**. The watcher is
what enforces this on the fallback side.

Because the primary may not be able to accept inbound connections, the
heartbeat direction is reversed: the primary's bot opens an outbound TCP
connection to the fallback every `HEARTBEAT_INTERVAL` seconds (default 10)
and closes it again — no protocol. The watcher on the fallback listens on
`WATCHER_LISTEN_PORT` (default 9876) and records each connection. If no
heartbeat arrives for `WATCHER_FAIL_THRESHOLD × WATCHER_POLL_INTERVAL`
seconds (default 30 s) the fallback starts its bot. As soon as a heartbeat
arrives again while the fallback is active, the fallback stops it
immediately (sub-second failback). When the fallback stops it sends a
final `ℹ️ Standby bot op <FALLBACK_NAME> gestopt` message to the group
chat.

### 1. Sync state with Syncthing

Install Syncthing on both hosts and share the bot folder, or at minimum:

- `data.json`
- `stats.json`
- `bot_state.pkl`

Recommended Syncthing ignore patterns (`.stignore` in the bot folder), so
logs, the Python virtualenv and the state of the admin messages about faults
don't get replicated. `faults.json` (dev: `faults.dev.json`) holds which
faults this host already reported to the admin, so each host keeps its own:

```
env/
log/
*.log
faults.json
faults.dev.json
.git/
__pycache__/
```

Set the folder's *fs watcher delay* to a few seconds (default is fine on a
LAN, raise it on a flakier WAN link). Conflict files (`*.sync-conflict-`*)
should never appear because the watcher guarantees only one bot runs at a
time; if they ever do, inspect them manually.

### 2. Install the bot on the fallback host

Follow the regular install instructions on the fallback host, but its
`dot-env` only needs the variables that maintenance mode uses (the rest
can be omitted):

```
BOT_TOKEN, BOT_TOKEN_DEV, CHAT_ID_GROUP, CHAT_ID_ADMIN,
LOG_TYPE, LOG_FOLDER, PRIMARY_NAME, FALLBACK_NAME
```

Instead of `files/plex-download-bot.service` install
`files/plex-download-bot-fallback.service` as
`/etc/systemd/system/plex-download-bot.service`. Reload systemd but **do not
enable it at boot** — the watcher is the only thing that should start it:

```
sudo systemctl daemon-reload
sudo systemctl disable plex-download-bot.service
```

### 3. Install the failover watcher on the fallback host

```
sudo cp files/plex-download-bot-watcher.env.template /etc/plex-download-bot-watcher.env
sudo chmod 600 /etc/plex-download-bot-watcher.env
sudo $EDITOR /etc/plex-download-bot-watcher.env   # adjust listen port, thresholds, etc.

sudo cp files/plex-download-bot-watcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now plex-download-bot-watcher.service
```

The watcher accepts heartbeats on `WATCHER_LISTEN_HOST:WATCHER_LISTEN_PORT`
(default `0.0.0.0:9876`) and runs a polling loop every
`WATCHER_POLL_INTERVAL` seconds (default 10 s) to evaluate silence. If no
heartbeat has arrived for `WATCHER_FAIL_THRESHOLD × WATCHER_POLL_INTERVAL`
seconds (default 30 s) it starts the fallback bot. The moment a fresh
heartbeat arrives while the fallback is active, it stops the fallback —
that's the immediate failback. Every `WATCHER_STATUS_LOG_EVERY` polls
(default 3 → every 30 s) the watcher writes an INFO summary line so you
can see in `journalctl -u plex-download-bot-watcher` that it's alive.
File logs go to `/var/log/plex-download-bot-watcher.log`.

Make sure `WATCHER_LISTEN_PORT` on the fallback is reachable from the
primary (firewall / NAT rules). On the primary, point
`HEARTBEAT_TARGET_HOST` at the fallback's direct address — a DNS name
that could resolve elsewhere would let the heartbeat go to the wrong
machine.