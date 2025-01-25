#!/usr/bin/python3


class Functions:

    def __init__(self, logger):

        # Set default values
        self.log = logger


    # Send standard text message
    async def send_message(self, msg, update, context, reply_markup=None, parse_mode='MarkdownV2') -> None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=msg,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )


    # Send message with GIF
    async def send_gif(self, caption, animation, update, context, reply_markup=None, parse_mode='MarkdownV2') -> None:
        await context.bot.send_animation(
            chat_id=update.effective_chat.id,
            caption=caption,
            animation=animation,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
