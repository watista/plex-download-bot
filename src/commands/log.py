#!/usr/bin/python3

""" /log: the log lines of a person or of one Interaction, for the Beheerder, one message at a time """

import asyncio
import html
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass
from datetime import date, datetime

import aiofiles
from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import BaseHandler, CallbackContext, CallbackQueryHandler, CommandHandler, filters

from src.faults import FaultKind
from src.interaction import ALPHABET, CODE_LENGTH
from src.log import files, get_logger, mask
from src.log.search import Found, Position, Query, from_library, search
from src.telegram_out import MAX_LENGTH, plain_text, rejects_formatting


log = get_logger(__name__)

# A row of a page is cut at this many characters
ROW_LENGTH = 200

# The most bytes Telegram takes in the callback_data of a button
CALLBACK_DATA_LENGTH = 64

# The argument of /log: only digits is a user ID, the form of a Code is a Code
USER_ID = re.compile(r"[0-9]+")
CODE = re.compile(f"[{ALPHABET}]{{{CODE_LENGTH}}}")

# A button of a page: earlier or later, about a person or a Code, from the position of a line, and the argument
BUTTON = re.compile(r"log:([el]):([pc]):([0-9]{8}):([0-9]+):(.+)", re.DOTALL)
EARLIER, LATER = "e", "l"
PERSON, INTERACTION = "p", "c"

# The kinds of Fout as the admin messages call them
KINDS = {"bug": "Bug", "disruption": "Disruption", "setup": "Setup"}

# In English whatever the locale of the host
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

USAGE = ("Usage: /log &lt;account name | user ID | code&gt;\n\n"
         "Shows the latest log lines of a person, or the lines of one interaction by the code in its error message.")


@dataclass(frozen=True)
class _Target:
    """ What /log shows: a person or one Interaction, with what the buttons call it.

    name is who the person is in the user list, None when only the lines can tell. in_logs_only is an argument that
    is neither a user ID nor an account in the user list: an account name in the lines, or else a Code.
    """
    query: Query
    kind: str
    argument: str
    name: str | None = None
    in_logs_only: bool = False


class LogCommand:
    """ /log <account name | user ID | code> and its buttons "⬅️ Earlier" and "Later ➡️".

    A stand-alone handler, like /help, so it also works in the middle of a Gesprek of the Beheerder. It reads the day
    files of env in folder, the user list in data_json, and names host as the one whose logs they are.
    """

    def __init__(self, env: str, folder: str, data_json: str, host: str, allowed_users: list[int]):
        self._env = env
        self._folder = folder
        self._data_json = data_json
        self._host = host
        self._allowed_users = list(allowed_users)

    def handlers(self) -> list[BaseHandler]:
        """ The handlers of /log and its buttons, only for allowed_users in the private chat. Anything else goes on to
        the catch-all, which writes the line ignored: register these before it. """
        beheerder = filters.User(self._allowed_users) & filters.ChatType.PRIVATE
        return [CommandHandler("log", self.log_command, beheerder),
                _BeheerderButtons(self.page_button, self._allowed_users)]

    async def log_command(self, update: Update, context: CallbackContext) -> None:
        """ /log: the latest lines that fit in one message, or a short explanation without an argument """
        parts = update.effective_message.text.split(None, 1)
        argument = parts[1].strip() if len(parts) > 1 else ""
        if not argument:
            log.info("admin command /log", event="admin_command", command="/log")
            await self._show(update, context, USAGE, None)
            return
        log.info(f"/log {argument}", event="admin_command", command="/log", argument=argument)

        users = await self._users()
        target = _person(argument, users)
        page = await self._page(target, users)
        if page is None and target.in_logs_only and CODE.fullmatch(argument.lower()):
            target = _interaction(argument.lower())
            page = await self._page(target, users)
        await self._show(update, context, *(page or (await self._nothing_found(target), None)))

    async def page_button(self, update: Update, context: CallbackContext) -> None:
        """ "⬅️ Earlier" or "Later ➡️": the page before or after the line in the button, in place of this one """
        query = update.callback_query
        await query.answer()
        direction, kind, day, offset, argument = BUTTON.fullmatch(query.data).groups()
        button = "earlier" if direction == EARLIER else "later"
        log.info(f"/log {argument}: {button}", event="admin_command", command="/log", argument=argument, button=button)

        users = await self._users()
        target = _person(argument, users) if kind == PERSON else _interaction(argument)
        position = Position(datetime.strptime(day, "%Y%m%d").date(), int(offset))
        if direction == EARLIER:
            page = await self._page(target, users, before=position)
        else:
            page = await self._page(target, users, after=position)
        await self._show(update, context, *(page or (await self._nothing_found(target), None)), edit=True)

    async def _page(self, target: _Target, users: dict[int, tuple[str, str]], before: Position | None = None,
                    after: Position | None = None) -> tuple[str, InlineKeyboardMarkup | None] | None:
        """ The page of the lines right before `before`, or right after `after`, or else the latest: as many as fit
        in one message. None without any line. """
        since = await self._since()

        def render(lines: list[Found]) -> str:
            return self._render(target, users, lines, since)

        def fits(lines: list[Found]) -> bool:
            # As Telegram counts: the text without the tags, in UTF-16
            return _length(render(lines)) <= MAX_LENGTH

        if after is not None:
            newer = [found async for found in self._search(target, after=after)]
            page = []
            for found in reversed(newer):
                if page and not fits(page + [found]):
                    return render(page), self._buttons(target, page, earlier=True, later=True)
                page.append(found)
            # The latest lines all fit: that is the latest page, with older lines too
            before = None

        page = []
        earlier = False
        async with aclosing(self._search(target, before=before)) as older:
            async for found in older:
                if page and not fits([found] + page):
                    earlier = True
                    break
                page.insert(0, found)
        if not page:
            return None
        return render(page), self._buttons(target, page, earlier=earlier, later=before is not None)

    async def _search(self, target: _Target, before: Position | None = None,
                      after: Position | None = None) -> AsyncIterator[Found]:
        """ The lines of the target from new to old; of a person without the lines of libraries """
        async with aclosing(search(self._folder, self._env, target.query, before=before, after=after)) as found_lines:
            async for found in found_lines:
                if target.kind == INTERACTION or not from_library(found.line):
                    yield found

    def _render(self, target: _Target, users: dict[int, tuple[str, str]], lines: list[Found],
                since: date | None) -> str:
        """ The page in HTML: a header with who it is, the lines per day with the oldest on top, and a footer """
        user_ids = sorted({found.line["user_id"] for found in lines if isinstance(found.line.get("user_id"), int)})
        names = {user_id: _tg_name(user_id, users, lines) for user_id in user_ids} if len(user_ids) > 1 else None

        if target.kind == INTERACTION:
            who = _who([found.line for found in lines], with_job=True)
            header = [f"📋 Code <code>{_escape(target.argument)}</code>" + (f" · {_escape(who)}" if who else "")]
        else:
            who = target.name or _who([found.line for found in lines], with_job=False) or target.argument
            header = [f"📋 <b>{_escape(who)}</b>"]
        if names is not None:
            header.append(" · ".join(f"{_escape(name)}: <code>{user_id}</code>" for user_id, name in names.items()))

        rows = []
        day = None
        for found in lines:
            if found.line.get("ts", "")[:10] != day:
                day = found.line.get("ts", "")[:10]
                rows.append(_day(day))
            rows.append(_row(found.line, names, with_exc_type=target.kind == INTERACTION))

        footer = []
        if target.kind == INTERACTION:
            footer.append(f"Traceback over SSH: <code>grep {_escape(target.argument)}</code>")
        footer.append(f"Logs on {_escape(self._host)}{_since(since)}")
        return "\n".join([*header, "", *rows, "", *footer])

    def _buttons(self, target: _Target, page: list[Found], earlier: bool,
                 later: bool) -> InlineKeyboardMarkup | None:
        """ The buttons to the lines before the oldest line of the page, and after the latest one. The position of
        that line goes in the button, so a button still works after a restart. """
        row = []
        if earlier and (data := _callback_data(EARLIER, target, page[0].position)):
            row.append(InlineKeyboardButton("⬅️ Earlier", callback_data=data))
        if later and (data := _callback_data(LATER, target, page[-1].position)):
            row.append(InlineKeyboardButton("Later ➡️", callback_data=data))
        return InlineKeyboardMarkup([row]) if row else None

    async def _nothing_found(self, target: _Target) -> str:
        """ What /log says when it finds no lines """
        if target.kind == INTERACTION:
            return f"Code {_escape(target.argument)} not found on {_escape(self._host)}"
        if target.in_logs_only:
            return f"Unknown user or code: {_escape(target.argument)}"
        return f"No log lines for {_escape(target.name or target.argument)} on {_escape(self._host)}" \
               f"{_since(await self._since())}"

    async def _since(self) -> date | None:
        """ The day of the oldest .jsonl file, None without one """
        days = await asyncio.to_thread(files.day_files, self._folder, self._env)
        return days[0][0] if days else None

    async def _users(self) -> dict[int, tuple[str, str]]:
        """ The user list of data.json: the account name and the Telegram name per user ID """
        async with aiofiles.open(self._data_json, "r") as file:
            data = json.loads(await file.read())
        users = {}
        for user_id, entry in data.get("user_id", {}).items():
            account, _, tg_name = str(entry).partition(",")
            if USER_ID.fullmatch(user_id) and account.strip():
                users[int(user_id)] = (account.strip(), tg_name.strip())
        return users

    async def _show(self, update: Update, context: CallbackContext, text: str, markup: InlineKeyboardMarkup | None,
                    edit: bool = False) -> None:
        """ Sends the page in HTML, or puts it in place of the page of the button.

        When Telegram rejects the formatting, the page goes once more as plain text, with the rejection on top. That
        rejection is a Bug, which gets a line but no admin message of its own, as in the verzendfunctie.
        """
        text = mask(text)
        try:
            await _put(update, context, text, ParseMode.HTML, markup, edit)
            return
        except BadRequest as e:
            if e.message.lower().startswith("message is not modified"):
                # The same page again, like after a double press
                return
            if not rejects_formatting(e):
                raise
            rejection = e.message
            log.error(f"Telegram rejected the HTML formatting of /log: {rejection}", exc_info=e, reason=rejection,
                      fault=FaultKind.BUG, service="telegram")
        await _put(update, context, f"⚠️ Telegram rejected the formatting: {rejection}\n\n{plain_text(text, 'HTML')}"
                                    [:MAX_LENGTH], None, markup, edit)


class _BeheerderButtons(CallbackQueryHandler):
    """ The buttons of /log, which only allowed_users press in the private chat: any other press goes on to the
    catch-all, which writes the line ignored """

    def __init__(self, callback: Callable[[Update, CallbackContext], Awaitable[None]], allowed_users: list[int]):
        super().__init__(callback, pattern=BUTTON)
        self._allowed_users = frozenset(allowed_users)

    def check_update(self, update: object) -> bool | object | None:
        if not isinstance(update, Update) or update.effective_user is None or update.effective_chat is None:
            return False
        if update.effective_user.id not in self._allowed_users or update.effective_chat.type != Chat.PRIVATE:
            return False
        return super().check_update(update)


def _person(argument: str, users: dict[int, tuple[str, str]]) -> _Target:
    """ The person an argument names: only digits is a user ID, then an account name in the user list in any case,
    with all its user IDs. Else it may be an account name that is only in the lines. """
    if USER_ID.fullmatch(argument):
        user_id = int(argument)
        account = users[user_id][0] if user_id in users else None
        return _Target(Query(user_ids=frozenset({user_id})), PERSON, argument, name=account)
    accounts = [account for account, _ in users.values() if account.casefold() == argument.casefold()]
    if accounts:
        user_ids = frozenset(user_id for user_id, (account, _) in users.items()
                             if account.casefold() == argument.casefold())
        return _Target(Query(user_ids=user_ids, account=accounts[0]), PERSON, argument, name=accounts[0])
    return _Target(Query(account=argument), PERSON, argument, in_logs_only=True)


def _interaction(code: str) -> _Target:
    return _Target(Query(code=code), INTERACTION, code)


def _who(lines: list[dict], with_job: bool) -> str | None:
    """ Who the lines are about: the job, when with_job, or else the person of the latest line with a user ID.

    A Gebruiker by account name, a Bezoeker by user ID plus Telegram name.
    """
    if with_job and (job := next((line["job"] for line in reversed(lines) if line.get("job")), None)):
        return str(job)
    for line in reversed(lines):
        if line.get("user_id") is None:
            continue
        if line.get("account"):
            return str(line["account"])
        return f"{line['user_id']} ({line['tg_name']})" if line.get("tg_name") else str(line["user_id"])
    return None


def _tg_name(user_id: int, users: dict[int, tuple[str, str]], lines: list[Found]) -> str:
    """ The Telegram name of a user ID: from the user list, or else from its lines as a Bezoeker """
    if users.get(user_id, ("", ""))[1]:
        return users[user_id][1]
    return next((str(found.line["tg_name"]) for found in lines
                 if found.line.get("user_id") == user_id and found.line.get("tg_name")), str(user_id))


def _day(day: str) -> str:
    """ The header of the lines of a day, like Mon 7 Dec """
    try:
        moment = date.fromisoformat(day)
    except ValueError:
        return _escape(day)
    return f"{DAYS[moment.weekday()]} {moment.day} {MONTHS[moment.month - 1]}"


def _row(line: dict, names: dict[int, str] | None, with_exc_type: bool) -> str:
    """ A line on a page: <b>14:05</b> msg, without the event.

    A Fout is short, with its kind, service and reason, and its Code to copy. With with_exc_type the type of the
    exception comes after it, but never the traceback. names puts the Telegram name in front, on a page with more
    than one user ID.
    """
    text = str(line.get("msg", ""))
    fout = line.get("fault") is not None and line.get("event") != "admin_message_sent"
    if fout:
        kind = KINDS.get(line["fault"], str(line["fault"]).capitalize())
        service = f" · {line['service']}" if line.get("service") else ""
        text = f"{kind}{service}: {line.get('reason') or text}"
    if with_exc_type and line.get("exc_type") and str(line["exc_type"]) not in text:
        text = f"{text} ({line['exc_type']})"
    if names is not None and isinstance(line.get("user_id"), int):
        text = f"{names[line['user_id']]}: {text}"
    if len(text) > ROW_LENGTH:
        text = text[:ROW_LENGTH - 1] + "…"

    row = f"<b>{_escape(line.get('ts', '')[11:16])}</b> {_escape(text)}"
    if not fout:
        return row
    code = f" <code>{_escape(line['interaction_id'])}</code>" if line.get("interaction_id") else ""
    return f"⚠️ {row}{code}"


def _callback_data(direction: str, target: _Target, position: Position) -> str | None:
    """ The callback_data of a button, None when the argument makes it too long for Telegram """
    data = f"log:{direction}:{target.kind}:{position.day:%Y%m%d}:{position.offset}:{target.argument}"
    return data if len(data.encode()) <= CALLBACK_DATA_LENGTH else None


def _length(page: str) -> int:
    """ The length of a page in HTML as Telegram counts it: the text without the tags, in UTF-16 code units """
    return len(plain_text(page, "HTML").encode("utf-16-le")) // 2


def _since(since: date | None) -> str:
    return f" since {since.isoformat()}" if since is not None else ""


def _escape(value: object) -> str:
    return html.escape(str(value), quote=False)


async def _put(update: Update, context: CallbackContext, text: str, fmt: str | None,
               markup: InlineKeyboardMarkup | None, edit: bool) -> None:
    """ Sends the text to the chat of the update, or puts it in place of the message of the button that was pressed """
    options = {"text": text, "parse_mode": fmt, "reply_markup": markup,
               "link_preview_options": LinkPreviewOptions(is_disabled=True)}
    if edit:
        message = update.callback_query.message
        await context.bot.edit_message_text(chat_id=message.chat_id, message_id=message.message_id, **options)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, **options)
