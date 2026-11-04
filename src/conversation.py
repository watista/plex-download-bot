#!/usr/bin/python3

""" Gesprek: the ConversationHandler of the bot, and the lines about the Gesprek itself.

Those are the lines of a command or a choice in a menu, of input that the bot ignores, and of a Gesprek that expires.
A handler writes a line of the first two kinds itself, with log.info(**command_or_choice_line(update)), so the line
has the logger and src of that handler.
"""

from collections.abc import Awaitable, Callable
from typing import NamedTuple

from telegram import Update
from telegram.ext import (BaseHandler, CallbackContext, CallbackQueryHandler, ConversationHandler, MessageHandler,
                          TypeHandler, filters)

from src.interaction import person_fields
from src.log import get_logger
from src.states import step_name


log = get_logger(__name__)

# Seconds without activity after which a Gesprek expires
EXPIRES_AFTER = 1800


class MenuButton(NamedTuple):
    """ A button of the start menu or the /help menu: which menu, and what the button means """
    menu: str
    meaning: str


# The buttons of both menus, per callback_data
MENU_BUTTONS = {
    "movie_request": MenuButton("start", "movie"),
    "serie_request": MenuButton("start", "series"),
    "account_request": MenuButton("start", "new account"),
    "info": MenuButton("start", "information"),
    "aanmelden_serie": MenuButton("start", "series updates on"),
    "afmelden_serie": MenuButton("start", "series updates off"),
    "aanmelden_updates": MenuButton("start", "general updates on"),
    "afmelden_updates": MenuButton("start", "general updates off"),
    "help_use": MenuButton("help", "how to use this bot"),
    "help_faq": MenuButton("help", "frequently asked questions"),
    "help_new_account": MenuButton("help", "new account"),
    "help_quality": MenuButton("help", "quality"),
    "help_other": MenuButton("help", "other"),
}


def command_of(update: Update) -> str:
    """ The command of a message, like /start: without the name of the bot and without its arguments """
    return update.effective_message.text.split()[0].split("@")[0]


def command_or_choice_line(update: Update, maintenance: bool = False) -> dict:
    """ The msg and fields of the line of a command, or of a button in the start menu or the /help menu.

    maintenance: the bot answers with the maintenance message.
    """
    outcome = "maintenance" if maintenance else None
    after = ": maintenance message" if maintenance else ""
    if update.callback_query:
        button = update.callback_query.data
        menu_button = MENU_BUTTONS.get(button)
        what = f"chose '{menu_button.meaning}' in the {menu_button.menu} menu" if menu_button else f"chose '{button}'"
        return {"msg": f"{what}{after}", "event": "menu_choice", "menu": menu_button and menu_button.menu,
                "button": button, "outcome": outcome}
    command = command_of(update)
    return {"msg": f"command {command}{after}", "event": "command", "command": command, "outcome": outcome}


def ignored_line(update: Update, step: str | None) -> dict:
    """ The msg and fields of the line of input that the bot ignores: the kind of input, the step of the Gesprek,
    and the value of the button or the command.

    Never the text: right there someone may send their password again after the Gesprek expired.
    """
    fields = {}
    if update.callback_query:
        kind, what, fields = "button", f"button '{update.callback_query.data}'", {"button": update.callback_query.data}
    elif update.effective_message and update.effective_message.text and filters.COMMAND.check_update(update):
        command = command_of(update)
        kind, what, fields = "command", f"command {command}", {"command": command}
    elif update.effective_message and update.effective_message.text:
        kind, what = "text", "text"
    else:
        kind, what = "other", "a message without text"
    where = f"at step {step}" if step else "outside a conversation"
    return {"msg": f"ignored {what} {where}", "event": "ignored", "input": kind, "step": step, **fields}


class Conversation(ConversationHandler):
    """ The ConversationHandler of the bot: it knows the step of each Gesprek, and writes a line when one expires.

    account_for gives the account name of a user ID, None for a Bezoeker: a Gesprek expires in a job, outside the
    Interaction of its last update.
    """

    def __init__(self, entry_points: list[BaseHandler], states: dict[object, list[BaseHandler]],
                 fallbacks: list[BaseHandler], account_for: Callable[[int], Awaitable[str | None]]):
        super().__init__(entry_points=entry_points,
                         states={**states, ConversationHandler.TIMEOUT: [TypeHandler(Update, self.expired)]},
                         fallbacks=fallbacks, conversation_timeout=EXPIRES_AFTER, per_chat=True, per_user=True)
        self._account_for = account_for

    def step(self, update: Update) -> str | None:
        """ The step that the Gesprek of the sender of this update is in, None when there is no Gesprek.

        PTB keeps the states in the protected _conversations, per key of _get_key, and has no public way to read
        them. In the handler of the state TIMEOUT the Gesprek is still in its last step: PTB ends it afterwards.
        """
        if not (update.effective_chat and update.effective_user):
            return None
        return step_name(self._conversations.get(self._get_key(update)))

    def catch_all(self) -> list[BaseHandler]:
        """ The handlers for input that no other handler takes: register them after all others """
        return [MessageHandler(filters.ALL, self.ignored), CallbackQueryHandler(self.ignored)]

    async def ignored(self, update: Update, context: CallbackContext) -> None:
        """ Input that no handler takes, in a Gesprek or outside one: only a line """
        log.info(**ignored_line(update, self.step(update)))

    async def expired(self, update: Update, context: CallbackContext) -> None:
        """ The handler of the state TIMEOUT. update is the last update of the Gesprek, which is still in its step. """
        user = update.effective_user
        step = self.step(update)
        log.info(f"conversation expired at step {step}", event="conversation_expired", step=step, user_id=user.id,
                 **await person_fields(user, self._account_for))
