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
LOG_TYPE: Log severity (Options are: ERROR, WARNING, INFO, DEBUG)
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

## High availability (primary + standby)

The bot is deployed on two hosts so users keep getting responses when the
primary server is down:

- **Primary** runs the bot in `--mode normal` and serves all features.
- **Standby** runs the bot in `--mode maintenance`, started only by
a watcher when the primary is unreachable. In maintenance mode Plex, Sonarr,
Radarr and Transmission are not used — any film/serie/serie-updates request
is answered with a "we're in maintenance" message. The admin `/message`,
`/message_all` and `/add_movie` commands keep working, as do `/start` (with
the maintenance reply for media options), `/help`, `/privacy`, the new
account flow, and `/aanmelden_updates` / `/afmelden_updates`.

Telegram allows only one active `getUpdates` poller per bot token, so
**only one of the two hosts may run the bot at any time**. The watcher is
what enforces this on the standby side.

### 1. Sync state with Syncthing

Install Syncthing on both hosts and share the bot folder, or at minimum:

- `data.json`
- `stats.json`
- `bot_state.pkl`

Recommended Syncthing ignore patterns (`.stignore` in the bot folder), so
logs and the Python virtualenv don't get replicated:

```
env/
log/
*.log
.git/
__pycache__/
```

Set the folder's *fs watcher delay* to a few seconds (default is fine on a
LAN, raise it on a flakier WAN link). Conflict files (`*.sync-conflict-`*)
should never appear because the watcher guarantees only one bot runs at a
time; if they ever do, inspect them manually.

### 2. Install the bot on shared

Follow the regular install instructions on the shared host, but on shared
the `dot-env` only needs the variables that maintenance mode uses (the rest
can be omitted):

```
BOT_TOKEN, BOT_TOKEN_DEV, CHAT_ID_GROUP, CHAT_ID_ADMIN,
LOG_TYPE, LOG_FOLDER
```

Instead of `files/plex-download-bot.service` install
`files/plex-download-bot-shared.service` as
`/etc/systemd/system/plex-download-bot.service`. Reload systemd but **do not
enable it at boot** — the watcher is the only thing that should start it:

```
sudo systemctl daemon-reload
sudo systemctl disable plex-download-bot.service
```

### 3. Install the failover watcher on shared

```
sudo cp files/plex-download-bot-watcher.env.template /etc/plex-download-bot-watcher.env
sudo chmod 600 /etc/plex-download-bot-watcher.env
sudo $EDITOR /etc/plex-download-bot-watcher.env   # set WATCHER_TARGET_HOST to AIVD

sudo cp files/plex-download-bot-watcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now plex-download-bot-watcher.service
```

The watcher TCP-probes the configured `WATCHER_TARGET_HOST:WATCHER_TARGET_PORT`
every `WATCHER_POLL_INTERVAL` seconds (default 10 s). After
`WATCHER_FAIL_THRESHOLD` consecutive failures (default 3 → 30 s) it starts
the standby bot. After `WATCHER_SUCCESS_THRESHOLD` consecutive successes
(default 3 → 30 s) once the primary returns it stops the standby bot,
handing polling back to AIVD. Logs go to
`/var/log/plex-download-bot-watcher.log` and `journalctl -u plex-download-bot-watcher`.

Pick the probe target carefully: probing Primary's HTTP port (80) detects host  
outages but not "host is up, services are dead". Probing a port more  
closely tied to the bot's dependencies (for example Plex on 32400) means a  
broken Plex also triggers failover, which keeps the maintenance message  
honest.