#!/usr/bin/python3

import asyncio
from telegram import Update
from telegram.ext import CallbackContext


class Privacy:

    def __init__(self, logger, functions):

        # Set default values
        self.log = logger
        self.function = functions

    async def privacy_command(self, update: Update, context: CallbackContext) -> None:

        # Debug usage log
        await self.log.logger(f"User started bot with /privacy - Username: {update.effective_user.first_name} - User ID: {update.effective_user.id}", False, "info", False)

        privacy_policy = f"""*Privacy Policy for Wouter Thuis-Server Bot*

*1. Introduction*
This Privacy Policy explains how the *Wouter Thuis-Server Bot* (the "Bot") operates and handles user data. By using the Bot, you agree to the terms outlined in this policy.

*2. Data Collection*
The Bot collects the following data:
- Telegram *Chat ID* – to identify and authorize users
- *Usernames* – for authentication and tracking requests
- *Media information* – details of requested media

*3. Data Usage*
The collected data is used to:
- Identify and authorize users
- Process media requests
- Retrieve information about requested media

*4. Data Storage*
- Chat IDs, usernames, and requested media details are stored for *365 days*.

*5. Data Sharing*
- No collected data is shared with third parties.
"""

        # Send the first part of the policy
        await self.function.send_message(privacy_policy, update, context)

        await asyncio.sleep(1)
        privacy_policy = """
*6. Data Security*
- All data access is protected by *fine-grained access control*.
- *No encryption* is applied to stored or in-transit data.

*7. User Rights*
- Users may request *data deletion* by contacting the server administrator.

*8. Access Restrictions*
- Only *verified users* have access to this bot.
- The stored information is already known to these users.

*Contact Information*
For any privacy concerns, contact the server admin.
"""

        # Send the second part of the policy
        return await self.function.send_message(privacy_policy, update, context)
