import argparse
import asyncio
from random import randint
from secrets import token_hex
from smtplib import SMTP, SMTPAuthenticationError
from unittest.mock import patch

import pytest
from aiohttp import ClientSession
from mail_devel import Service
from mail_devel import __main__ as main

MAIL = """
Content-Type: multipart/mixed; boundary="------------6S5GIA0a7bmD9z4YzFLV1oIL"
Message-ID: <ce22c843-2061-33e9-403c-40ef9261a2cf@example.org>
Date: Sat, 18 Feb 2023 15:01:13 +0100
MIME-Version: 1.0
Content-Language: en-US
To: test@localhost
From: test <test@example.org>
Subject: hello

This is a multi-part message in MIME format.
--------------6S5GIA0a7bmD9z4YzFLV1oIL
Content-Type: text/plain; charset=UTF-8; format=flowed
Content-Transfer-Encoding: 7bit

hello world<br/>hello world 2

--------------6S5GIA0a7bmD9z4YzFLV1oIL
Content-Type: text/plain; charset=UTF-8; name="att abc.txt"
Content-Disposition: attachment; filename="att abc.txt"
Content-Transfer-Encoding: base64

aGVsbG8gd29ybGQ=

--------------6S5GIA0a7bmD9z4YzFLV1oIL--
""".strip()


def unused_ports(n: int = 1):
    if n == 1:
        return randint(4000, 14000)
    return [randint(4000, 14000) for _ in range(n)]


async def build_test_service(pw, **kwargs):
    args = ["--host", "127.0.0.1", "--user", "test", "--password", pw]
    for key, value in kwargs.items():
        args.extend((f"--{key.replace('_', '-')}", str(value)))
    args = Service.parse(args)
    return await Service.init(args)


@pytest.mark.asyncio
async def test_mail_devel_no_password():
    with pytest.raises(argparse.ArgumentError):
        Service.parse([])


@pytest.mark.asyncio
async def test_mail_devel_smtp():
    smtp_port, http_port = unused_ports(2)
    pw = token_hex(10)
    service = await build_test_service(pw, smtp_port=smtp_port, http_port=http_port)
    mailbox = await service.mailbox_set.get_mailbox("INBOX")
    sent = await service.mailbox_set.get_mailbox("SENT")

    async with service.start():
        await asyncio.sleep(0.1)

        assert not [msg async for msg in mailbox.messages()]

        with SMTP("localhost", port=smtp_port) as smtp:
            smtp.sendmail("test@example.org", "test@example.org", MAIL)

        assert len([msg async for msg in mailbox.messages()]) == 1
        assert len([msg async for msg in sent.messages()]) == 0


@pytest.mark.asyncio
async def test_mail_devel_http():
    smtp_port, http_port = unused_ports(2)
    pw = token_hex(10)
    service = await build_test_service(pw, smtp_port=smtp_port, http_port=http_port)
    mailbox = await service.mailbox_set.get_mailbox("INBOX")
    await service.mailbox_set.get_mailbox("SENT")

    assert service.frontend.load_resource("index.html")
    assert service.frontend.load_resource("main.css")
    assert service.frontend.load_resource("main.js")

    async with service.start():
        await asyncio.sleep(0.1)

        assert not [msg async for msg in mailbox.messages()]

        with SMTP("localhost", port=smtp_port) as smtp:
            smtp.sendmail("test@example.org", "test@example.org", MAIL)

        async with ClientSession(f"http://localhost:{http_port}") as session:
            for route in ["/", "/main.css", "/main.js"]:
                async with session.get(route) as response:
                    assert response.status == 200

            async with session.get("/unknown.css") as response:
                assert response.status == 404

            async with session.get("/api") as response:
                assert response.status == 200
                mailbox = await response.json()
                assert len(mailbox) == 2
                assert "INBOX" in mailbox

            async with session.get("/api/INBOX") as response:
                assert response.status == 200
                mbox = await response.json()
                assert len(mbox) == 1
                assert mbox[0]["uid"] == 101

            async with session.get("/api/INBOX/101") as response:
                assert response.status == 200
                msg = await response.json()
                assert msg
                assert msg["attachments"]

            async with session.get("/api/INBOX/101/reply") as response:
                assert response.status == 200
                msg = await response.json()
                assert msg["header"]["to"] == "test <test@example.org>"
                assert msg["header"]["message-id"].endswith("@mail-devel")

            msg["body"] = "hello"
            async with session.post("/api", json=msg) as response:
                assert response.status == 200

            async with session.get("/api/INBOX") as response:
                assert response.status == 200
                mbox = await response.json()
                assert len(mbox) == 2

            async with session.get("/api/INBOX/101/attachment/att abc.txt") as response:
                assert response.status == 200
                assert await response.text() == "hello world"

            async with session.get("/api/INBOX/101/flags") as response:
                assert response.status == 200
                assert await response.json() == []

            async with session.put("/api/INBOX/101/flags/unseen") as response:
                assert response.status == 200
                assert await response.json() == ["unseen"]

            async with session.get("/api/INBOX/101/flags") as response:
                assert response.status == 200
                assert await response.json() == ["unseen"]

            async with session.delete("/api/INBOX/101/flags/unseen") as response:
                assert response.status == 200
                assert await response.json() == []

            async with session.put("/api/INBOX/999/flags/unseen") as response:
                assert response.status == 404

            async with session.get("/api/INBOX/101/attachment/unknown.txt") as response:
                assert response.status == 404

            async with session.get("/api/INBOX/999/attachment/att abc.txt") as response:
                assert response.status == 404

            async with session.get("/api/INBOX/999") as response:
                assert response.status == 404


@pytest.mark.asyncio
async def test_mail_devel_smtp_auth():
    port = unused_ports()
    pw = token_hex(10)
    service = await build_test_service(pw, smtp_port=port)
    mailbox = await service.mailbox_set.get_mailbox("INBOX")

    await asyncio.sleep(0.2)
    async with service.start():
        await asyncio.sleep(0.1)

        with SMTP("localhost", port=port) as smtp:
            smtp.sendmail("test@example.org", "test@example.org", MAIL)

        assert len([msg async for msg in mailbox.messages()]) == 1

        with SMTP("localhost", port=port) as smtp:
            smtp.login("test", pw)
            smtp.sendmail("test@example.org", "test@example.org", MAIL)

        assert len([msg async for msg in mailbox.messages()]) == 2

        with pytest.raises(SMTPAuthenticationError), SMTP(
            "localhost", port=port
        ) as smtp:
            smtp.login("invalid", pw)


@pytest.mark.asyncio
async def test_main_sleep_forever():
    with patch("asyncio.sleep", autospec=True) as mock:
        mock.side_effect = [None] * 10 + [GeneratorExit()]
        with pytest.raises(GeneratorExit):
            await main.sleep_forever()
        assert mock.call_count == 11  # 10 calls + GeneratorExit


@pytest.mark.asyncio
async def test_main():
    pw = token_hex(10)
    args = ["--host", "127.0.0.1", "--user", "test", "--password", pw]
    args = Service.parse(args)
    with patch("mail_devel.__main__.sleep_forever", autospec=True) as mock:
        await main.run(args)
        mock.assert_called_once()
