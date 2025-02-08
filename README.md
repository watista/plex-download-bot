[![GPLv3 License](https://img.shields.io/badge/License-GPL%20v3-yellow.svg)](https://opensource.org/licenses/)
![Python Version](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)

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
