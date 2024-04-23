import argparse
import asyncio
from contextlib import asynccontextmanager
from imaplib import IMAP4
from random import randint
from secrets import token_hex
from smtplib import SMTP, SMTPAuthenticationError
from threading import Thread
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
To: test@localhost, second <second@localhost>
Cc: cc@localhost
Bcc: bcc@localhost
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


class ThreadResult(Thread):
    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None):
        if not kwargs:
            kwargs = {}

        super().__init__(group, target, name, args, kwargs)
        self._return = None

    def run(self):
        if self._target is not None:
            self._return = self._target(*self._args, **self._kwargs)

    def join(self, *args):
        super().join(*args)
        return self._return


def unused_ports(n: int = 1):
    if n == 1:
        return randint(4000, 14000)
    return [randint(4000, 14000) for _ in range(n)]


async def build_test_service(pw, **kwargs):
    args = ["--host", "127.0.0.1", "--user", "test", "--password", pw]
    for key, value in kwargs.items():
        key = key.replace("_", "-")
        if value is not None:
            args.extend((f"--{key}", str(value)))
        else:
            args.append(f"--{key}")
    args = Service.parse(args)
    return await Service.init(args)


def imap_login_test(port, user, password, mail_count=None):
    try:
        with IMAP4("localhost", port=port) as mbox:
            mbox.login(user, password)
            mbox.select()

            if mail_count is None:
                return True

            _type, data = mbox.search(None, "ALL")
            mails = data[0].split()
            return mail_count == len(mails)
    except Exception:
        return False


@asynccontextmanager
async def prepare_http_test():
    imap_port, smtp_port, http_port = unused_ports(3)
    pw = token_hex(10)
    service = await build_test_service(
        pw, imap_port=imap_port, smtp_port=smtp_port, http_port=http_port
    )
    account = await service.mailboxes.get(service.demo_user)
    service.mailboxes.id_of_user(service.demo_user)
    mailbox = await account.get_mailbox("INBOX")
    account.id_of_mailbox("INBOX")
    await account.get_mailbox("SENT")
    account.id_of_mailbox("INBOX")

    assert service.frontend.load_resource("index.html")
    assert service.frontend.load_resource("main.css")
    assert service.frontend.load_resource("main.js")

    async with service.start():
        await asyncio.sleep(0.5)

        assert not [msg async for msg in mailbox.messages()]

        with SMTP("localhost", port=smtp_port) as smtp:
            smtp.sendmail("test@example.org", "test@example.org", MAIL)

        async with ClientSession(f"http://localhost:{http_port}") as session:
            yield session, service


@pytest.mark.asyncio
async def test_mail_devel_no_password():
    with pytest.raises(argparse.ArgumentError):
        Service.parse([])


@pytest.mark.asyncio
async def test_mail_devel_service():
    smtp_port = unused_ports()
    pw = token_hex(10)
    service = await build_test_service(pw, smtp_port=smtp_port, no_http=None)
    account = await service.mailboxes.get("main")
    mailbox = await account.get_mailbox("INBOX")
    sent = await account.get_mailbox("SENT")

    async with service.start():
        await asyncio.sleep(0.1)

        assert not [msg async for msg in mailbox.messages()]

        with SMTP("localhost", port=smtp_port) as smtp:
            smtp.sendmail("test@example.org", "test@example.org", MAIL)

        assert len([msg async for msg in mailbox.messages()]) == 1
        assert len([msg async for msg in sent.messages()]) == 0


@pytest.mark.asyncio
async def test_mail_devel_http_static():
    async with prepare_http_test() as (session, _service):
        for route in ["/", "/main.css", "/main.js"]:
            async with session.get(route) as response:
                assert response.status == 200

        async with session.get("/unknown.css") as response:
            assert response.status == 404


@pytest.mark.asyncio
async def test_mail_devel_http():
    async with prepare_http_test() as (session, service):
        async with session.get("/api") as response:
            assert response.status == 200
            users = await response.json()
            assert len(users) == 1
            assert service.demo_user in users.values()

        async with session.get("/api/1") as response:
            assert response.status == 200
            users = await response.json()
            assert len(users) == 2
            assert "INBOX" in users.values()

        async with session.get("/api/1/1") as response:
            assert response.status == 200
            mbox = await response.json()
            assert len(mbox) == 1
            assert mbox[0]["uid"] == 101

        async with session.get("/api/1/1/101") as response:
            assert response.status == 200
            msg = await response.json()
            assert msg
            assert msg["attachments"]

        async with session.get("/api/1/1/999") as response:
            assert response.status == 404


@pytest.mark.asyncio
async def test_mail_devel_http_reply():
    async with prepare_http_test() as (session, _service):
        async with session.get("/api/1/1/101/reply") as response:
            assert response.status == 200
            msg = await response.json()
            assert msg["header"]["to"] == "test <test@example.org>"
            assert msg["header"]["message-id"].endswith("@mail-devel")

        async with session.get("/api/1/1/999/reply") as response:
            assert response.status == 404

        msg.update(
            {
                "body": "hello",
                "attachments": [
                    {
                        "mimetype": "text/plain",
                        "name": "file.txt",
                        "content": "aGVsbG8gd29ybGQ=",
                    }
                ],
            }
        )
        async with session.post("/api/1/1", json=msg) as response:
            assert response.status == 200

        async with session.post("/api/1/1", json={}) as response:
            assert response.status == 400

        async with session.post("/api/1/1", json=[]) as response:
            assert response.status == 400

        async with session.get("/api/1/1") as response:
            assert response.status == 200
            mbox = await response.json()
            assert len(mbox) == 2


@pytest.mark.asyncio
async def test_mail_devel_http_flagging():
    async with prepare_http_test() as (session, _service):
        async with session.get("/api/1/1/101/flags") as response:
            assert response.status == 200
            assert await response.json() == []

        async with session.put("/api/1/1/101/flags/unseen") as response:
            assert response.status == 200
            assert await response.json() == ["unseen"]

        async with session.get("/api/1/1/101/flags") as response:
            assert response.status == 200
            assert await response.json() == ["unseen"]

        async with session.delete("/api/1/1/101/flags/unseen") as response:
            assert response.status == 200
            assert await response.json() == []

        async with session.put("/api/1/1/999/flags/unseen") as response:
            assert response.status == 404


@pytest.mark.asyncio
async def test_mail_devel_http_attachment():
    async with prepare_http_test() as (session, _service):
        print(_service.mailboxes.user_mapping)
        async with session.get("/api/1/1/101/attachment/att abc.txt") as response:
            assert response.status == 200
            assert await response.text() == "hello world"

        async with session.get("/api/1/1/101/attachment/unknown.txt") as response:
            assert response.status == 404

        async with session.get("/api/1/1/999/attachment/att abc.txt") as response:
            assert response.status == 404


@pytest.mark.asyncio
async def test_mail_devel_smtp_auth():
    port = unused_ports()
    pw = token_hex(10)
    service = await build_test_service(pw, smtp_port=port, no_http=None)
    account = await service.mailboxes.get("test")
    mailbox = await account.get_mailbox("INBOX")

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
async def test_mail_devel_smtp_auth_multi_user():
    iport, sport = unused_ports(2)
    pw = token_hex(10)
    service = await build_test_service(
        pw, imap_port=iport, smtp_port=sport, multi_user=None, no_http=None
    )

    await asyncio.sleep(0.2)
    async with service.start():
        await asyncio.sleep(0.1)

        with SMTP("localhost", port=sport) as smtp:
            smtp.login("test", pw)
            smtp.sendmail("test@example.org", "test@example.org", MAIL)

        with SMTP("localhost", port=sport) as smtp:
            smtp.login("multi", pw)
            smtp.sendmail("test@example.org", "test@example.org", MAIL)


@pytest.mark.asyncio
async def test_mail_devel_imap_auth():
    iport, sport = unused_ports(2)
    pw = token_hex(10)
    service = await build_test_service(
        pw, imap_port=iport, smtp_port=sport, no_http=None
    )

    await asyncio.sleep(0.2)
    async with service.start():
        await asyncio.sleep(0.1)

        valid = ThreadResult(target=imap_login_test, args=(iport, "test", pw))
        invalid = ThreadResult(target=imap_login_test, args=(iport, "invalid", pw))
        valid.start()
        invalid.start()
        await asyncio.sleep(0.5)
        assert valid.join()
        assert not invalid.join()


@pytest.mark.asyncio
async def test_mail_devel_imap_auth_multi_user():
    iport, sport = unused_ports(2)
    pw = token_hex(10)
    service = await build_test_service(
        pw, imap_port=iport, smtp_port=sport, multi_user=None, no_http=None
    )

    await asyncio.sleep(0.2)
    async with service.start():
        await asyncio.sleep(0.5)

        valid1 = ThreadResult(target=imap_login_test, args=(iport, "test", pw))
        valid2 = ThreadResult(target=imap_login_test, args=(iport, "other", pw))
        invalid = ThreadResult(target=imap_login_test, args=(iport, "test", "invalid"))
        valid1.start()
        valid2.start()
        invalid.start()
        await asyncio.sleep(0.5)
        assert valid1.join()
        assert valid2.join()
        assert not invalid.join()


@pytest.mark.asyncio
async def test_mail_devel_imap_auth_multi_user_mails():
    iport, sport = unused_ports(2)
    pw = token_hex(10)
    service = await build_test_service(
        pw,
        user="test@example.org",
        imap_port=iport,
        smtp_port=sport,
        multi_user=None,
        no_http=None,
    )

    expectations = [
        ("test@example.org", 0),
        ("test@localhost", 1),
        ("cc@localhost", 1),
        ("bcc@localhost", 1),
    ]

    await asyncio.sleep(0.2)
    async with service.start():
        await asyncio.sleep(0.2)
        with SMTP("localhost", port=sport) as smtp:
            smtp.sendmail("test@example.org", "test@example.org", MAIL)

        await asyncio.sleep(0.2)

        threads = [
            ThreadResult(target=imap_login_test, args=(iport, account, pw, mail_count))
            for account, mail_count in expectations
        ]
        for thread in threads:
            thread.start()
        await asyncio.sleep(0.5)
        for thread in threads:
            assert thread.join()


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
    sport, iport = unused_ports(2)

    args = Service.parse(
        [
            "--host",
            "127.0.0.1",
            "--user",
            "test",
            "--password",
            pw,
            "--smtp-port",
            str(sport),
            "--imap-port",
            str(iport),
            "--no-http",
        ]
    )
    with patch("mail_devel.__main__.sleep_forever", autospec=True) as mock:
        await main.run(args)
        mock.assert_called_once()
