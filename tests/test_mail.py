import argparse
import asyncio
import os
import re
from contextlib import asynccontextmanager
from email import message_from_string
from imaplib import IMAP4
from random import randint
from secrets import token_hex
from smtplib import SMTP, SMTPAuthenticationError
from threading import Thread
from typing import Any, AsyncGenerator, Callable, Iterable, Tuple
from unittest.mock import patch

import pytest
from aiohttp import ClientSession
from mail_devel import Service, __main__ as main
from mail_devel.builder import Builder
from mail_devel.smtp import Flag

MAIL = """
Content-Type: multipart/mixed; boundary="------------6S5GIA0a7bmD9z4YzFLV1oIL"
Message-ID: <ce22c843-2061-33e9-403c-40ef9261a2cf@example.org>
Date: Sat, 18 Feb 2023 15:01:13 +0100
MIME-Version: 1.0
Content-Language: en-US
To: test@localhost, second <second@localhost>
Cc: cc@localhost
Bcc: bcc@localhost
Reply-To: xx@localhost
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
    def __init__(  # pylint: disable=R0917
        self,
        group: None = None,
        target: Callable[[int, str, str, int | None], bool] | None = None,
        name: str | None = None,
        args: Iterable[Any] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        if not kwargs:
            kwargs = {}

        self._args = args
        self._kwargs = kwargs
        self._target = target
        super().__init__(group, target, name, args, kwargs)
        self._return: Any = None

    def run(self) -> None:
        if self._target is not None:
            self._return = self._target(*self._args, **self._kwargs)

    def join(self, *args: Any) -> Any:
        super().join(*args)
        return self._return


def unused_ports(n: int = 1) -> list[int]:
    if n == 1:
        return [randint(4000, 14000)]
    return [randint(4000, 14000) for _ in range(n)]


async def build_test_service(pw: str, **kwargs: Any) -> Service:
    args = ["--host", "127.0.0.1", "--user", "test", "--password", pw]
    for key, value in kwargs.items():
        key = key.replace("_", "-")
        if value is not None:
            args.extend((f"--{key}", str(value)))
        else:
            args.append(f"--{key}")
    namespace = Service.parse(args)
    return await Service.init(namespace)


def imap_login_test(
    port: int, user: str, password: str, mail_count: int | None = None
) -> bool:
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
async def prepare_http_test() -> AsyncGenerator[Tuple[ClientSession, Service], None]:
    imap_port, smtp_port, http_port = unused_ports(3)
    pw = token_hex(10)
    service = await build_test_service(
        pw, imap_port=imap_port, smtp_port=smtp_port, http_port=http_port
    )
    assert service.mailboxes
    assert service.demo_user
    account = await service.mailboxes.get(service.demo_user)
    mailbox = await account.get_mailbox("INBOX")
    await account.get_mailbox("SENT")

    assert service.frontend
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
async def test_no_password() -> None:
    with pytest.raises(argparse.ArgumentError):
        Service.parse([])


@pytest.mark.asyncio
async def test_service() -> None:
    (smtp_port,) = unused_ports()
    pw = token_hex(10)
    service = await build_test_service(pw, smtp_port=smtp_port, no_http=None)
    assert service.mailboxes

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
async def test_http_static() -> None:
    async with prepare_http_test() as (session, _service):
        for route in ["/", "/main.css", "/main.js"]:
            async with session.get(route) as response:
                assert response.status == 200

        async with session.get("/unknown.css") as response:
            assert response.status == 404


@pytest.mark.asyncio
async def test_websocket() -> None:
    async with prepare_http_test() as (session, _service):
        async with session.ws_connect("/websocket") as ws:
            await ws.send_str("invalid json")
            await ws.send_json([])

            await ws.send_json({"command": "config"})
            data = await ws.receive_json()
            assert data["command"] == "config"
            assert data["data"]

            await ws.send_json({"command": "close"})


@pytest.mark.asyncio
async def test_http_upload() -> None:
    async with prepare_http_test() as (session, service):
        async with session.ws_connect("/websocket") as ws:
            mail_no_id = "\n".join(
                x for x in MAIL.splitlines() if "Message-ID" not in x
            )

            await ws.send_json(
                {
                    "command": "upload_mails",
                    "account": service.demo_user,
                    "mailbox": "INBOX",
                    "mails": [{"data": MAIL}, {"data": mail_no_id}],
                }
            )
            data = await ws.receive_json()
            assert data["command"] == "list_mails"
            assert len(data["data"]["mails"]) == 3


@pytest.mark.asyncio
async def test_http() -> None:
    async with prepare_http_test() as (session, service):
        async with session.ws_connect("/websocket") as ws:
            await ws.send_json({"command": "list_accounts"})
            data = await ws.receive_json()
            assert data["command"] == "list_accounts"
            assert data["data"]["accounts"] == [service.demo_user]

            await ws.send_json(
                {"command": "list_mailboxes", "account": service.demo_user}
            )
            data = await ws.receive_json()
            assert data["command"] == "list_mailboxes"
            assert data["data"]["mailboxes"] == ["INBOX", "SENT"]

            await ws.send_json(
                {"command": "list_mails", "account": service.demo_user, "mailbox": None}
            )
            data = await ws.receive_json()
            assert data["command"] == "list_mails"
            assert len(data["data"]["mails"]) == 1
            assert data["data"]["mails"][0]["uid"] == 101

            await ws.send_json(
                {"command": "list_mails", "account": None, "mailbox": None}
            )
            with pytest.raises(TimeoutError):
                await ws.receive_json(timeout=0.25)

            await ws.send_json(
                {
                    "command": "get_mail",
                    "account": service.demo_user,
                    "mailbox": "INBOX",
                    "uid": 101,
                }
            )
            data = await ws.receive_json()
            assert data["command"] == "get_mail"
            assert data["data"]["uid"] == 101
            assert data["data"]["mail"]
            assert data["data"]["mail"]["attachments"]

            await ws.send_json(
                {
                    "command": "get_mail",
                    "account": service.demo_user,
                    "mailbox": "INBOX",
                    "uid": 999,
                }
            )
            with pytest.raises(TimeoutError):
                await ws.receive_json(timeout=0.25)


@pytest.mark.asyncio
async def test_http_random() -> None:
    async with prepare_http_test() as (session, service):
        async with session.ws_connect("/websocket") as ws:
            await ws.send_json(
                {
                    "command": "random_mail",
                    "account": service.demo_user,
                    "mailbox": "INBOX",
                }
            )
            data = await ws.receive_json()
            assert data["command"] == "random_mail"
            assert data["data"]["mail"]["header"]
            assert data["data"]["mail"]["body_plain"]


@pytest.mark.asyncio
async def test_http_reply() -> None:
    async with prepare_http_test() as (session, service):
        async with session.ws_connect("/websocket") as ws:
            await ws.send_json(
                {
                    "command": "reply_mail",
                    "account": service.demo_user,
                    "mailbox": "INBOX",
                    "uid": 101,
                }
            )
            data = await ws.receive_json()
            assert data["command"] == "reply_mail"
            msg = data["data"]["mail"]
            assert msg["header"]["to"] == "test <test@example.org>"
            assert "@mail-devel" in msg["header"]["message-id"]

            await ws.send_json(
                {
                    "command": "reply_mail",
                    "account": service.demo_user,
                    "mailbox": "INBOX",
                    "uid": 999,
                }
            )
            with pytest.raises(TimeoutError):
                await ws.receive_json(timeout=0.25)

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
            await ws.send_json(
                {
                    "command": "list_mails",
                    "account": service.demo_user,
                    "mailbox": "INBOX",
                }
            )
            data = await ws.receive_json()
            assert data["command"] == "list_mails"

            await ws.send_json(
                {
                    "command": "send_mail",
                    "account": service.demo_user,
                    "mailbox": "INBOX",
                    "mail": msg,
                }
            )
            data = await ws.receive_json()
            assert data["command"] == "list_mails"
            assert len(data["data"]["mails"]) == 2


@pytest.mark.asyncio
async def test_http_flagging() -> None:
    async with prepare_http_test() as (session, service):
        async with session.ws_connect("/websocket") as ws:
            await ws.send_json(
                {
                    "command": "get_mail",
                    "account": service.demo_user,
                    "mailbox": "INBOX",
                    "uid": 101,
                }
            )
            data = await ws.receive_json()
            assert data["command"] == "get_mail"
            assert data["data"]["mail"]["uid"] == 101
            assert data["data"]["mail"]["flags"] == []

            await ws.send_json(
                {
                    "command": "flag_mail",
                    "account": service.demo_user,
                    "mailbox": "INBOX",
                    "uid": 101,
                    "method": "set",
                    "flag": "seen",
                }
            )
            data = await ws.receive_json()
            assert data["command"] == "list_mails"
            assert data["data"]["mails"][0]["uid"] == 101
            assert data["data"]["mails"][0]["flags"] == ["seen"]

            await ws.send_json(
                {
                    "command": "flag_mail",
                    "account": service.demo_user,
                    "mailbox": "INBOX",
                    "uid": 101,
                    "method": "invalid",
                    "flag": "seen",
                }
            )
            data = await ws.receive_json()
            assert data["command"] == "list_mails"
            assert data["data"]["mails"][0]["uid"] == 101
            assert data["data"]["mails"][0]["flags"] == ["seen"]

            await ws.send_json(
                {
                    "command": "flag_mail",
                    "account": service.demo_user,
                    "mailbox": "INBOX",
                    "uid": 101,
                    "method": "unset",
                    "flag": "seen",
                }
            )
            data = await ws.receive_json()
            assert data["command"] == "list_mails"
            assert data["data"]["mails"][0]["uid"] == 101
            assert data["data"]["mails"][0]["flags"] == []

            await ws.send_json(
                {
                    "command": "flag_mail",
                    "account": service.demo_user,
                    "mailbox": "INBOX",
                    "uid": 999,
                    "method": "unset",
                    "flag": "seen",
                }
            )
            with pytest.raises(TimeoutError):
                await ws.receive_json(timeout=0.25)


@pytest.mark.asyncio
async def test_http_mailboxes() -> None:
    async with prepare_http_test() as (session, service):
        async with session.ws_connect("/websocket") as ws:
            frontend = service.frontend
            assert frontend

            await ws.send_json(
                {
                    "command": "list_mailboxes",
                    "account": service.demo_user,
                }
            )
            data = await ws.receive_json()
            assert data["command"] == "list_mailboxes"
            mailboxes = data["data"]["mailboxes"]

            await ws.send_json(
                {
                    "command": "add_mailbox",
                    "account": service.demo_user,
                    "name": "test",
                }
            )

            data = await ws.receive_json()
            assert data["command"] == "list_mailboxes"
            assert set(data["data"]["mailboxes"]) == {*mailboxes, "test"}

            await ws.send_json(
                {
                    "command": "add_mailbox",
                    "account": service.demo_user,
                    "name": "test",
                    "parent": "test",
                }
            )

            data = await ws.receive_json()
            assert data["command"] == "list_mailboxes"
            assert set(data["data"]["mailboxes"]) == {*mailboxes, "test", "test/test"}

            await ws.send_json(
                {
                    "command": "delete_mailbox",
                    "account": service.demo_user,
                    "name": "test",
                }
            )

            data = await ws.receive_json()
            assert data["command"] == "list_mailboxes"
            assert set(data["data"]["mailboxes"]) == set(mailboxes)


@pytest.mark.asyncio
async def test_http_attachment() -> None:
    async with prepare_http_test() as (session, service):
        async with session.ws_connect("/websocket") as ws:
            await ws.send_json(
                {
                    "command": "get_mail",
                    "account": service.demo_user,
                    "mailbox": "INBOX",
                    "uid": 101,
                }
            )
            data = await ws.receive_json()
            assert data["command"] == "get_mail"
            assert data["data"]["uid"] == 101
            assert data["data"]["mail"]
            assert data["data"]["mail"]["attachments"]

            att = data["data"]["mail"]["attachments"][0]
            async with session.get(att["url"]) as response:
                assert response.status == 200
                assert await response.text() == "hello world"

            url = att["url"].rsplit("/", 1)[0]
            async with session.get(f"{url}/unknown.txt") as response:
                assert response.status == 404

            async with session.get("/attachment/invalid/att abc.txt") as response:
                assert response.status == 404


@pytest.mark.asyncio
async def test_responder() -> None:
    pw = token_hex(10)
    service = await build_test_service(pw, no_http=None)
    assert service.handler

    assert service.handler._load_responder_from_module("invalid-reply") is None
    assert service.handler._load_responder_from_module("invalid_reply") is None

    assert not service.handler.responder
    service.handler.load_responder("reply_once")
    assert service.handler.responder

    service.handler.responder = None
    service.handler.load_responder("reply_always")
    assert service.handler.responder


@pytest.mark.asyncio
async def test_memory_handler() -> None:
    pw = token_hex(10)
    service = await build_test_service(pw, no_http=None)
    assert service.handler

    flag = Flag("\\Seen")
    assert service.handler._convert_flags(None) == frozenset()
    assert service.handler._convert_flags([]) == frozenset()
    assert service.handler._convert_flags(["seen"]) == frozenset([flag])
    assert service.handler._convert_flags([b"seen"]) == frozenset([flag])
    assert service.handler._convert_flags([flag]) == frozenset([flag])


@pytest.mark.asyncio
async def test_smtp_auth() -> None:
    (port,) = unused_ports()
    pw = token_hex(10)
    service = await build_test_service(pw, smtp_port=port, no_http=None)
    assert service.mailboxes

    account = await service.mailboxes.get("test")
    mailbox = await account.get_mailbox("INBOX")

    await asyncio.sleep(0.2)
    async with service.start():
        assert service.handler
        await asyncio.sleep(0.1)

        with SMTP("localhost", port=port) as smtp:
            smtp.sendmail("test@example.org", "test@example.org", MAIL)

        assert len([msg async for msg in mailbox.messages()]) == 1

        with SMTP("localhost", port=port) as smtp:
            smtp.login("test", pw)
            smtp.sendmail("test@example.org", "test@example.org", MAIL)

        await asyncio.sleep(0.1)

        assert len([msg async for msg in mailbox.messages()]) == 2

        with (
            pytest.raises(SMTPAuthenticationError),
            SMTP("localhost", port=port) as smtp,
        ):
            smtp.login("invalid", pw)

        service.handler.load_responder("reply_once")
        service.handler.flagged_seen = True
        assert callable(service.handler.responder)
        with SMTP("localhost", port=port) as smtp:
            smtp.login("test", pw)
            smtp.sendmail("test@example.org", "test@example.org", MAIL)

        msgs = [msg async for msg in mailbox.messages()]
        assert len(msgs) == 4
        assert Flag(b"\\Seen") in msgs[-2].permanent_flags
        assert Flag(b"\\Seen") not in msgs[-1].permanent_flags

        with patch.dict(os.environ, {"MAIL_USE_REPLY_TO": "on"}):
            with SMTP("localhost", port=port) as smtp:
                smtp.login("test", pw)
                smtp.sendmail("test@example.org", "test@example.org", MAIL)

            msgs = [msg async for msg in mailbox.messages()]
            assert len(msgs) == 6


@pytest.mark.asyncio
async def test_smtp_auth_multi_user() -> None:
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
async def test_imap_auth() -> None:
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
async def test_imap_auth_multi_user() -> None:
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
async def test_imap_auth_multi_user_mails() -> None:
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
async def test_main_sleep_forever() -> None:
    with patch("asyncio.sleep", autospec=True) as mock:
        mock.side_effect = [None] * 10 + [GeneratorExit()]
        with pytest.raises(GeneratorExit):
            await main.sleep_forever()
        assert mock.call_count == 11  # 10 calls + GeneratorExit


@pytest.mark.asyncio
async def test_main() -> None:
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


@pytest.mark.asyncio
async def test_builder() -> None:
    msg_id_regex = re.compile(r"^<[0-9a-fA-F\-]+@mail-devel>$")
    addr_regex = re.compile(r"^[0-9a-fA-F]+@mail-devel$")

    assert msg_id_regex.match(Builder.message_id())
    assert addr_regex.match(Builder.mail_address())

    mail = message_from_string(MAIL)
    reply = Builder.reply_mail(mail)
    assert msg_id_regex.match(reply["Message-Id"])
    assert addr_regex.match(reply["From"])
    assert reply["To"] == mail["From"]

    reply = Builder.reply_mail(mail, use_reply_to=True)
    assert reply["To"] == mail["Reply-To"]

    mail.replace_header("Reply-To", "")
    reply = Builder.reply_mail(mail, use_reply_to=True)
    assert reply["To"] == mail["From"]
