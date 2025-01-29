#!/usr/bin/python3

import re


class Functions:

    def __init__(self, logger):

        # Set default values
        self.log = logger


    # Send standard text message
    async def send_message(self, text, update, context, reply_markup=None, parse_mode='MarkdownV2') -> None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=self.escape_markdown(text),
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )


    # Send message with GIF
    async def send_gif(self, caption, animation, update, context, reply_markup=None, parse_mode='MarkdownV2') -> None:
        await context.bot.send_animation(
            chat_id=update.effective_chat.id,
            caption=self.escape_markdown(caption),
            animation=animation,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )


    # Send message with image
    async def send_image(self, caption, photo, update, context, reply_markup=None, parse_mode='MarkdownV2') -> None:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            caption=self.escape_markdown(caption),
            photo=photo,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )

    def escape_markdown(self, text:str) -> str:
        special_chars = r'_\[\]()~`>#+-=|{}.!'
        return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)
