import hashlib
import json
import logging
import os
import secrets
import ssl
import uuid
from email import header, message_from_bytes, message_from_string, policy
from email.errors import MessageDefect
from email.message import Message
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from importlib import resources
from typing import Any, Tuple

import aiohttp
from aiohttp import web
from aiohttp.web import Request, Response, WebSocketResponse
from pymap.backend.dict.mailbox import Message as PyMapMessage
from pymap.parsing.specials import FetchRequirement
from pymap.parsing.specials.flag import Flag

from .builder import Builder
from .mailbox import TestMailboxDict
from .utils import VERSION, extract_payload

_logger = logging.getLogger(__name__)


Mail = dict[str, Any]


def decode_header(value: str) -> str:
    return str(header.make_header(header.decode_header(value)))


def decode_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        try:
            return payload.decode()
        except UnicodeDecodeError:
            return ""

    if isinstance(payload, str):
        return payload

    return ""


def flags_to_api(flags: frozenset[Flag]) -> list[str]:
    return [f.value.decode().strip("\\").lower() for f in flags]


async def run_app(
    api: web.Application,
    host: str | None = None,
    port: int | None = None,
    ssl_context: ssl.SSLContext | None = None,
) -> web.AppRunner:
    app = web.AppRunner(
        api,
        access_log_format='%a "%r" %s %b "%{Referer}i" "%{User-Agent}i"',
    )
    await app.setup()

    site = web.TCPSite(
        app,
        host=host,
        port=port,
        reuse_address=True,
        reuse_port=True,
        ssl_context=ssl_context,
    )
    await site.start()
    return app


# pylint: disable=R0917
class Frontend:
    def __init__(
        self,
        mailboxes: TestMailboxDict,
        *,
        user: str,
        host: str = "",
        port: int = 8080,
        devel: str = "",
        flagged_seen: bool = False,
        ensure_message_id: bool = True,
        client_max_size: int = 1 << 20,
        multi_user: bool = False,
    ) -> None:
        self.mailboxes: TestMailboxDict = mailboxes
        self.api: web.Application | None = None
        self.host: str = host
        self.port: int = port
        self.user: str = user
        self.devel: str = devel
        self.flagged_seen: bool = flagged_seen
        self.ensure_message_id = ensure_message_id
        self.client_max_size: int = client_max_size
        self.multi_user: bool = multi_user

        self.mail_cache: dict[str, Tuple[str, str, int]] = {}

    def load_resource(self, resource: str) -> str:
        if self.devel:  # pragma: no cover
            with open(os.path.join(self.devel, resource), encoding="utf-8") as fp:
                return fp.read()

        package = f"{__package__}.resources"
        res = resources.files(package).joinpath(resource)
        if not res.is_file():
            raise FileNotFoundError()

        return res.read_text(encoding="utf-8")

    async def start(self) -> web.AppRunner:
        self.api = web.Application(client_max_size=self.client_max_size)

        self.api.add_routes(
            [
                web.get("/", self._page_index),
                web.get(r"/{static:.*\.(css|js)}", self._page_static),
                web.get("/websocket", self._websocket),
                web.get(
                    r"/attachment/{mail:.*}/{attachment:.*}", self._download_attachment
                ),
            ]
        )

        return await run_app(
            self.api,
            host=self.host or None,
            port=self.port,
        )

    async def _websocket(self, request: Request) -> WebSocketResponse:
        ws = WebSocketResponse()
        await ws.prepare(request)

        _logger.info(f"Connected websocket: {request.remote}")
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue

            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue

            if not isinstance(data, dict) or not data.get("command"):
                continue

            command = data.pop("command")
            if command == "close":
                await ws.close()
                continue

            func = getattr(self, f"on_{command}", None)
            if func and callable(func):
                await func(ws, **data)  # pylint: disable=E1102

        _logger.info(f"Disconnected websocket: {request.remote}")
        return ws

    async def _page_index(self, request: Request) -> Response:  # pylint: disable=W0613
        try:
            return Response(
                body=self.load_resource("index.html"),
                content_type="text/html",
            )
        except FileNotFoundError as e:  # pragma: no cover
            _logger.error("File 'index.html' not in resources")
            raise web.HTTPNotFound() from e

    async def _page_static(self, request: Request) -> Response:
        static = request.match_info["static"]
        if static.endswith(".js"):
            mimetype = "text/javascript"
        elif static.endswith(".css"):
            mimetype = "text/css"
        else:  # pragma: no cover
            raise web.HTTPNotFound()

        try:
            return Response(body=self.load_resource(static), content_type=mimetype)
        except FileNotFoundError as e:  # pragma: no cover
            _logger.error(f"File {static!r} not in resources")
            raise web.HTTPNotFound() from e

    async def _message_content(self, msg: PyMapMessage) -> bytes:
        return bytes((await msg.load_content(FetchRequirement.CONTENT)).content)

    def message_hash(self, content: bytes | str) -> str:
        if isinstance(content, str):
            content = content.encode()

        return hashlib.sha512(content).hexdigest()

    async def _convert_message(
        self,
        msg: PyMapMessage,
        *,
        account: str,
        mailbox: str,
        full: bool = False,
        message: Message | None = None,
    ) -> Mail:
        if not message:
            content = await self._message_content(msg)
            message = message_from_bytes(content)
        else:
            content = message.as_bytes()

        result = {
            "uid": msg.uid,
            "flags": flags_to_api(msg.permanent_flags),
            "header": {k.lower(): decode_header(v) for k, v in message.items()},
            "date": msg.internal_date.isoformat(),
        }

        if not full:
            return result

        msg_hash = self.message_hash(content)
        self.mail_cache[msg_hash] = (account, mailbox, msg.uid)

        attachments = []
        if message.is_multipart():
            for part in message.walk():
                ctype = part.get_content_type()
                cdispo = part.get_content_disposition()

                if cdispo == "attachment":
                    name = part.get_filename()
                    attachments.append(
                        {"name": name, "url": f"/attachment/{msg_hash}/{name}"}
                    )
                elif ctype == "text/plain":
                    result["body_plain"] = decode_payload(part)
                elif ctype == "text/html":
                    result["body_html"] = decode_payload(part)
        elif message.get_content_type() == "text/html":
            result["body_html"] = decode_payload(message)
        else:
            result["body_plain"] = decode_payload(message)

        result["attachments"] = attachments
        result["content"] = bytes(content).decode()
        return result

    async def on_config(self, ws: WebSocketResponse) -> None:
        await ws.send_json(
            {
                "command": "config",
                "data": {
                    "multi_user": self.multi_user,
                    "flagged_seen": self.flagged_seen,
                    "version": VERSION,
                },
            }
        )

    async def on_list_accounts(self, ws: WebSocketResponse) -> None:
        await ws.send_json(
            {
                "command": "list_accounts",
                "data": {
                    "accounts": await self.mailboxes.list(),
                },
            }
        )

    async def on_list_mailboxes(self, ws: WebSocketResponse, account: str) -> None:
        acc = await self.mailboxes.get(account)
        mailboxes = await acc.list_mailboxes()
        await ws.send_json(
            {
                "command": "list_mailboxes",
                "data": {
                    "account": account,
                    "mailboxes": sorted(m.name for m in mailboxes.list()),
                },
            }
        )

    async def on_add_mailbox(
        self,
        ws: WebSocketResponse,
        account: str,
        name: str,
        parent: str | bool = False,
    ) -> None:
        if not account or not name:
            return

        try:
            acc = self.mailboxes[account]
            await acc.add_mailbox(f"{parent}/{name}" if parent else name)
        except (IndexError, KeyError, ValueError):  # pragma: no cover
            return

        await self.on_list_mailboxes(ws, account)

    async def on_delete_mailbox(
        self,
        ws: WebSocketResponse,
        account: str,
        name: str,
    ) -> None:
        if not account or not name:
            return

        if name == "INBOX":
            return

        try:
            acc = self.mailboxes[account]

            mailboxes = await acc.list_mailboxes()
            to_delete = [m.name for m in mailboxes.list() if m.name.startswith(name)]
            for mbox_name in sorted(to_delete, reverse=True):
                await acc.delete_mailbox(mbox_name)
        except (IndexError, KeyError):  # pragma: no cover
            return

        await self.on_list_mailboxes(ws, account)

    async def on_move_mail(
        self,
        ws: WebSocketResponse,
        account: str,
        mailbox_from: str,
        mailbox_to: str,
        mail_uid: int,
    ) -> None:
        if not account:
            return

        if not mailbox_from or not mailbox_to or mailbox_from == mailbox_to:
            return

        try:
            acc = self.mailboxes[account]

            mbox_from = await acc.get_mailbox(mailbox_from)
            mbox_to = await acc.get_mailbox(mailbox_to)
        except (IndexError, KeyError):  # pragma: no cover
            return

        await mbox_from.move(mail_uid, mbox_to)

        await self.on_list_mails(ws, account, mailbox_from)

    async def on_list_mails(
        self, ws: WebSocketResponse, account: str | None, mailbox: str | None
    ) -> None:
        if not account:
            return

        if not mailbox:
            mailbox = "INBOX"

        try:
            mbox = await self.mailboxes[account].get_mailbox(mailbox)
        except (IndexError, KeyError):  # pragma: no cover
            return

        result = [
            await self._convert_message(msg, account=account, mailbox=mailbox)
            async for msg in mbox.messages()
        ]

        result.sort(key=lambda x: x["date"], reverse=True)

        await ws.send_json(
            {
                "command": "list_mails",
                "data": {"account": account, "mailbox": mailbox, "mails": result},
            }
        )

    async def on_get_mail(
        self, ws: WebSocketResponse, account: str, mailbox: str, uid: int
    ) -> None:
        try:
            mbox = await self.mailboxes[account].get_mailbox(mailbox)
        except (IndexError, KeyError):  # pragma: no cover
            return

        async for msg in mbox.messages():
            if msg.uid == uid:
                await ws.send_json(
                    {
                        "command": "get_mail",
                        "data": {
                            "account": account,
                            "mailbox": mailbox,
                            "uid": uid,
                            "mail": await self._convert_message(
                                msg,
                                account=account,
                                mailbox=mailbox,
                                full=True,
                            ),
                        },
                    }
                )
                break

    async def on_random_mail(
        self, ws: WebSocketResponse, account: str, mailbox: str
    ) -> None:
        headers = {
            "subject": f"Random Subject [{secrets.token_hex(8)}]",
            "message-id": Builder.message_id(),
            "to": account,
            "from": Builder.mail_address(),
        }
        _logger.info("Randomized mail")
        await ws.send_json(
            {
                "command": "random_mail",
                "data": {
                    "account": account,
                    "mailbox": mailbox,
                    "mail": {
                        "header": headers,
                        "body_plain": f"Body {uuid.uuid4()}",
                    },
                },
            }
        )

    async def on_reply_mail(
        self, ws: WebSocketResponse, account: str, mailbox: str, uid: int
    ) -> None:
        try:
            mbox = await self.mailboxes[account].get_mailbox(mailbox)
        except (IndexError, KeyError):  # pragma: no cover
            return

        async for msg in mbox.messages():
            if msg.uid == uid:
                content = await self._message_content(msg)
                reply = Builder.reply_mail(message_from_bytes(content))

                message = await self._convert_message(
                    msg,
                    account=account,
                    mailbox=mailbox,
                    full=True,
                    message=reply,
                )

                await ws.send_json(
                    {
                        "command": "reply_mail",
                        "data": {
                            "account": account,
                            "mailbox": mailbox,
                            "uid": uid,
                            "mail": message,
                        },
                    }
                )
                break

    async def on_flag_mail(
        self,
        ws: WebSocketResponse,
        account: str,
        mailbox: str,
        uid: int,
        method: str,
        flag: str,
    ) -> None:
        try:
            mbox = await self.mailboxes[account].get_mailbox(mailbox)
            method = method.lower()

            if method in ("unset", "set"):
                flags = [Flag(b"\\" + flag.title().encode())]
            else:
                flags = []
        except (IndexError, KeyError):  # pragma: no cover
            return

        async for msg in mbox.messages():
            if msg.uid != uid:
                continue

            if method == "unset":
                msg.permanent_flags = msg.permanent_flags.difference(flags)
            elif method == "set":
                msg.permanent_flags = msg.permanent_flags.union(flags)

            _logger.info(
                f"{method.title()} flag {flag} of mail {uid}: {flags}: {msg.permanent_flags}"
            )

            await self.on_list_mails(ws, account, mailbox)
            break

    async def on_upload_mails(
        self,
        ws: WebSocketResponse,
        account: str | None,
        mailbox: str | None,
        mails: list[Mail],
    ) -> None:
        compat_strict = policy.compat32.clone(raise_on_defect=True)
        counter = 0
        for mail in mails:
            try:
                msg = message_from_string(mail["data"], policy=compat_strict)

                if not msg["Message-Id"] and self.ensure_message_id:
                    msg.add_header("Message-Id", Builder.message_id())

                await self.mailboxes.append(
                    msg,
                    flags=frozenset({Flag(b"\\Seen")} if self.flagged_seen else []),
                    mailbox=mailbox or "INBOX",
                )
                counter += 1
            except MessageDefect:
                continue

        if counter:
            _logger.info(f"Uploaded {counter} mails")
            await self.on_list_mails(ws, account, mailbox)

    async def on_send_mail(
        self,
        ws: WebSocketResponse,
        account: str | None,
        mailbox: str | None,
        mail: Mail,
    ) -> None:
        header, body = map(mail.get, ("header", "body"))
        if not isinstance(header, dict) or not isinstance(body, str):
            return

        message = MIMEMultipart()
        message.attach(MIMEText(body))

        for key, value in header.items():
            if key.strip() and value.strip():
                message.add_header(key.title(), value)

        if not message["Message-Id"] and self.ensure_message_id:
            message.add_header("Message-Id", Builder.message_id())

        for att in mail.get("attachments", []):
            part = MIMEBase(*(att["mimetype"] or "text/plain").split("/"))
            part.set_payload(att["content"])
            part.add_header("Content-Transfer-Encoding", "base64")
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{att["name"]}"',  # noqa: B907
            )
            message.attach(part)

        await self.mailboxes.append(
            message,
            flags=frozenset({Flag(b"\\Seen")} if self.flagged_seen else []),
            mailbox=mailbox or "INBOX",
        )
        _logger.info("New mail sent")
        await self.on_list_mails(ws, account, mailbox)

    async def _download_attachment(self, request: Request) -> Response:
        try:
            mail_hash = request.match_info["mail"]
            if mail_hash not in self.mail_cache:
                raise web.HTTPNotFound()

            account, mailbox, uid = self.mail_cache[mail_hash]
            attachment = request.match_info["attachment"]
            mbox = await self.mailboxes[account].get_mailbox(mailbox)
        except (IndexError, KeyError) as e:  # pragma: no cover
            self.mail_cache.pop(mail_hash, None)
            raise web.HTTPNotFound() from e

        message = None
        async for msg in mbox.messages():
            if msg.uid == uid:
                content = await self._message_content(msg)
                message = message_from_bytes(content)

        if not message or not message.is_multipart():
            raise web.HTTPNotFound()

        for part in message.walk():
            if (
                part.get_content_disposition() == "attachment"
                and part.get_filename() == attachment
            ):
                cte = part.get("Content-Transfer-Encoding")
                body = extract_payload(part, bool(cte))
                return web.Response(
                    body=body,
                    headers={
                        "Content-Type": part.get("Content-Type", ""),
                        "Content-Disposition": part.get("Content-Disposition", ""),
                    },
                )

        raise web.HTTPNotFound()
