# Plex download Telegram bot
This projects uses Plex, Sonarr, Radarr and Transmission to automate download requests for your Plex server.

[![GPLv3 License](https://img.shields.io/badge/License-GPL%20v3-yellow.svg)](https://opensource.org/licenses/)
![Python Version](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)

## Getting started
### Environment variables and tokens
Copy the dot-env.template to the root folder with the name `dot-env` and fill in the variables
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
Copy the contents of `data.json.template` to `data.json` and the contents of `stats.json.template` to `stats.json`

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
