#!/usr/bin/python3

import requests
import json
import os


class Sonarr:


    def __init__(self, logger):

        # Create the log class
        self.log = logger
        self.token = os.getenv('SONARR_API')
        self.sonarr_url = "https://sonarr.wouterpaas.nl/api/v3/"


    def get(self, url_string: str): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?

        # Build request URL
        url = self.sonarr_url + url_string + "&" + self.token

        # Make the request
        try:
            response = requests.request("GET", url, headers={}, data={})

            # Log and send Telegram message if request was unsuccesfull
            if not response.ok:
                self.log.logger(f"Not OK response for Sonarr api GET. Error: {response.status_code} {response.reason} {response.text} - Url: {url}", False, "error", False)
                return False

            # Return the response if request was succesfull
            return response

        # Log and send Telegram message if anything went wrong
        except Exception as e:
            self.log.logger(f"Fout opgetreden tijdens een Sonarr api GET. Error: {' '.join(e.args)} - Url: {url}", False, "error", False)
            return False


    def post(self, url_string: str, payload): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?

        # Build request URL
        url = self.sonarr_url + url_string + "&" + self.token

        # Make the request
        try:
            response = requests.request("POST", url, headers={'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}, data=payload)

            # Log and send Telegram message if request was unsuccesfull
            if not response.ok:
                self.log.logger(f"Not OK response for Sonarr api POST. Error: {response.status_code} {response.reason} {response.text} - Url: {url}", False, "error", False)
                return False

            # Return the response if request was succesfull
            return response

        # Log and send Telegram message if anything went wrong
        except Exception as e:
            self.log.logger(f"Fout opgetreden tijdens een Sonarr api POST. Error: {' '.join(e.args)} - Url: {url}", False, "error", False)
            return False

    def lookup_by_name(self, movie_name: str): # HIER NOG TYPE HINT MEEGEVEN, IS HET EEN JSON OF DICT OFZO?

        # Build url_string and make the request
        lookup = self.get(f"/movie/lookup?term={movie_name}")

        # Check if return value is empty
        if not lookup:
            self.log.logger(f"❌ *Error while fetching movie list for term {movie_name}. Check the error log for more information. ❌", False, "error")
            return {}

        # Return the data
        return lookup.json()
