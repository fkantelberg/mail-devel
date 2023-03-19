import argparse
import asyncio
from imaplib import IMAP4
from secrets import token_hex
from smtplib import SMTP

import pytest
from mail_devel import Service


@pytest.mark.asyncio
async def test_mail_devel_no_password():
    with pytest.raises(argparse.ArgumentError):
        Service.parse([])


@pytest.mark.asyncio
async def test_mail_devel():
    pw = token_hex(10)
    args = Service.parse(["--host", "127.0.0.1", "--user", "test", "--password", pw])
    service = await Service.init(args)

    async with service.start():
        await asyncio.sleep(0.1)

        with SMTP("localhost", port=4025) as smtp:
            smtp.sendmail("test@example.org", "test@example.org", "hello world")
