#!/usr/bin/python3

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.ext import ConversationHandler

from src.commands.account import Account
from src.log import setup_logging
from src.states import REQUEST_ACCOUNT_EMAIL, REQUEST_ACCOUNT_PHONE, REQUEST_ACCOUNT_REFER
from test_conversation import message
from test_log import MAIN, LogFolder


class AccountTest(LogFolder, unittest.IsolatedAsyncioTestCase):
    """ The questions of an account request """

    def setUp(self):
        super().setUp()
        setup_logging("dev", "INFO", str(self.folder), False)
        self.enterContext(self.at("2026-11-03T14:05:12+01:00"))
        self.enterContext(patch("src.commands.account.asyncio.sleep", AsyncMock()))

        functions = MagicMock(send_message=AsyncMock(), sanitize_text=lambda text: text.replace("*", ""))
        self.telegram = MagicMock(send_admin_message=AsyncMock())
        self.account = Account(functions, self.telegram)

    async def test_only_the_name_of_an_account_request_gets_into_the_log(self):
        context = MagicMock(user_data={})

        states = [await self.account.request_account(message("Piet *Puk*", 777, "Piet"), context),
                  await self.account.request_account_email(message("piet@example.com", 777, "Piet"), context),
                  await self.account.request_account_phone(message("0612345678", 777, "Piet"), context),
                  await self.account.request_account_refer(message("via Klaas", 777, "Piet"), context)]

        self.assertEqual(states, [REQUEST_ACCOUNT_EMAIL, REQUEST_ACCOUNT_PHONE, REQUEST_ACCOUNT_REFER,
                                  ConversationHandler.END])
        lines = self.lines("account_request")
        self.assertEqual([line["msg"] for line in lines], [
            "account request: name 'Piet *Puk*'",
            "account request: email answered",
            "account request: phone answered",
            "account request: via answered",
        ])
        self.assertEqual([line["question"] for line in lines], ["name", "email", "phone", "via"])
        self.assertEqual(lines[0]["name"], "Piet *Puk*")
        for secret in ("piet@example.com", "0612345678", "Klaas"):
            self.assertNotIn(secret, self.raw(MAIN))

        # The Beheerder gets them all, in Telegram
        [(text, about)] = [call.args for call in self.telegram.send_admin_message.await_args_list]
        self.assertEqual(about, "account request")
        for answer in ("Piet Puk", "piet@example.com", "0612345678", "via Klaas"):
            self.assertIn(answer, text)


if __name__ == "__main__":
    unittest.main()
