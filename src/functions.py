#!/usr/bin/python3

import re
import asyncio
from telegram.error import RetryAfter

class Functions:

    def __init__(self, logger):

        # Set default values
        self.log = logger


    # Send standard text message
    async def send_message(self, text: str, update, context, reply_markup=None, parse_mode='MarkdownV2', regular=True) -> None:

        # Check if the user_id is regular or special
        chat_id = update.effective_user.id if regular else update

        # Split all words on spaces
        words = text.split(' ')
        messages = []
        current_chunk = ""

        # Loop through all words to create chunks
        for word in words:
            if len(current_chunk) + len(word) + 1 > 1024:
                messages.append(current_chunk)
                # Start a new chunk
                current_chunk = word
            else:
                # Append word to current chunk
                current_chunk += (" " if current_chunk else "") + word

        # Add last chunk if not empty
        if current_chunk:
            messages.append(current_chunk)

        for message in messages:
            while True:
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=self.escape_markdown(message, parse_mode),
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                        disable_web_page_preview=True
                    )
                    break
                except RetryAfter as e:
                    await asyncio.sleep(e.retry_after)
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=self.escape_markdown(message, parse_mode),
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                        disable_web_page_preview=True
                    )

        # Debug log
        await self.log.logger(text, False, "debug", False)


    # Send message with GIF
    async def send_gif(self, caption: str, animation, update, context, reply_markup=None, parse_mode='MarkdownV2') -> None:
        try:
            await context.bot.send_animation(
                chat_id=update.effective_user.id,
                caption=self.escape_markdown(caption, parse_mode)[:1024],
                animation=animation,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await context.bot.send_animation(
                chat_id=update.effective_user.id,
                caption=self.escape_markdown(caption, parse_mode)[:1024],
                animation=animation,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )

        # Debug log
        await self.log.logger(caption, False, "debug", False)


    # Send message with image
    async def send_image(self, caption: str, photo, update, context, reply_markup=None, parse_mode='MarkdownV2') -> None:
        try:
            await context.bot.send_photo(
                chat_id=update.effective_user.id,
                caption=self.escape_markdown(caption, parse_mode)[:1024],
                photo=photo,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await context.bot.send_photo(
                chat_id=update.effective_user.id,
                caption=self.escape_markdown(caption, parse_mode)[:1024],
                photo=photo,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )

        # Debug log
        await self.log.logger(caption, False, "debug", False)


    # Escape reserverd characters for Markdown V2
    def escape_markdown(self, text: str, parse_mode: str) -> str:
        if parse_mode == "MarkdownV2":
            special_chars = r'\[\]()~`>#+-=|{}.!'
            return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)
        else:
            return text


    # Sanitize text and remove _ and *
    def sanitize_text(self, text: str) -> str:
        return text.replace("*", "").replace("_", "")
