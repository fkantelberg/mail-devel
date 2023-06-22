import logging
import sys
import uuid
from datetime import datetime
from email import message_from_bytes
from email.message import EmailMessage
from importlib import resources

from aiohttp import web
from aiohttp.web import Request, Response
from pymap.backend.dict import MailboxSet
from pymap.backend.dict.mailbox import Message
from pymap.parsing.message import AppendMessage
from pymap.parsing.specials.flag import Flag

_logger = logging.getLogger(__name__)


def flags_to_api(flags):
    return [f.value.decode().strip("\\").lower() for f in flags]


class Frontend:
    def __init__(
        self,
        mailbox_set: MailboxSet,
        user: str,
        host: str = "",
        port: int = 8080,
        devel: bool = False,
        flagged_seen: bool = False,
    ):
        self.mailbox_set = mailbox_set
        self.api = None
        self.devel = devel
        self.host, self.port = host, port
        self.user = user
        self.flagged_seen = flagged_seen

    def load_resource(self, resource: str) -> str:
        if self.devel:
            with open(resource, encoding="utf-8") as fp:
                return fp.read()

        package = f"{__package__}.resources"

        if sys.version_info < (3, 9):
            if not resources.is_resource(package, resource):
                raise FileNotFoundError()

            return resources.read_text(package, resource)

        res = resources.files(package).joinpath(resource)
        if not res.is_file():
            raise FileNotFoundError()

        return res.read_text(encoding="utf-8")

    async def start(self) -> None:
        self.api = web.Application()

        self.api.add_routes(
            [
                web.get("/", self._page_index),
                web.get(r"/{static:.*\.(css|js)}", self._page_static),
                web.post(r"/api", self._api_post),
                web.get(r"/api", self._api_index),
                web.get(r"/api/{mailbox}", self._api_mailbox),
                web.get(r"/api/{mailbox}/{uid:\d+}", self._api_message),
                web.get(r"/api/{mailbox}/{uid:\d+}/reply", self._api_reply),
                web.get(
                    r"/api/{mailbox}/{uid:\d+}/attachment/{attachment}",
                    self._api_attachment,
                ),
                web.get(r"/api/{mailbox}/{uid:\d+}/flags", self._api_flag),
                web.put(r"/api/{mailbox}/{uid:\d+}/flags/{flag}", self._api_flag),
                web.delete(r"/api/{mailbox}/{uid:\d+}/flags/{flag}", self._api_flag),
            ]
        )

        return await web._run_app(
            self.api,
            host=self.host,
            port=self.port,
            access_log_format='%a "%r" %s %b "%{Referer}i" "%{User-Agent}i"',
            reuse_address=True,
            reuse_port=True,
            print=None,
        )

    async def _page_index(self, request: Request) -> Response:  # pylint: disable=W0613
        try:
            return Response(
                body=self.load_resource("index.html"),
                content_type="text/html",
            )
        except FileNotFoundError as e:
            _logger.error("File 'index.html' not in resources")
            raise web.HTTPNotFound() from e

    async def _page_static(self, request: Request) -> Response:
        static = request.match_info["static"]
        if static.endswith(".js"):
            mimetype = "text/javascript"
        elif static.endswith(".css"):
            mimetype = "text/css"
        else:
            raise web.HTTPNotFound()

        try:
            return Response(body=self.load_resource(static), content_type=mimetype)
        except FileNotFoundError as e:
            _logger.error(f"File {static!r} not in resources")
            raise web.HTTPNotFound() from e

    async def _convert_message(self, msg: Message, full: bool = False) -> dict:
        content = bytes((await msg.load_content([])).content)

        message = message_from_bytes(content)
        result = {
            "uid": msg.uid,
            "flags": flags_to_api(msg.permanent_flags),
            "header": {k.lower(): v for k, v in message.items()},
            "date": msg.internal_date.isoformat(),
        }

        if not full:
            return result

        result["attachments"] = []
        if message.is_multipart():
            for part in message.walk():
                ctype = part.get_content_type()
                cdispo = part.get_content_disposition()

                if cdispo == "attachment":
                    result["attachments"].append(part.get_filename())
                elif ctype == "text/plain":
                    result["body_plain"] = part.get_payload(decode=True).decode()
                elif ctype == "text/html":
                    result["body_html"] = part.get_payload(decode=True).decode()
        elif message.get_content_type() == "text/html":
            result["body_html"] = message.get_payload(decode=True).decode()
        else:
            result["body_plain"] = message.get_payload(decode=True).decode()

        result["content"] = bytes(content).decode()
        return result

    async def _api_index(self, request: Request) -> Response:  # pylint: disable=W0613
        mailboxes = await self.mailbox_set.list_mailboxes()
        return web.json_response([e.name for e in mailboxes.list()])

    async def _api_post(self, request: Request) -> Response:
        data = await request.json()
        if not isinstance(data, dict):
            raise web.HTTPBadRequest()

        header, body = map(data.get, ("header", "body"))
        if not isinstance(header, dict) or not isinstance(body, str):
            raise web.HTTPBadRequest()

        message = EmailMessage()
        for key, value in header.items():
            if key.strip() and value.strip():
                message.add_header(key.title(), value)

        message.set_content(body)

        mailbox = await self.mailbox_set.get_mailbox("INBOX")
        await mailbox.append(
            AppendMessage(
                literal=str(message).encode(),
                when=datetime.now(),
                flag_set=frozenset({Flag(b"\\Seen")} if self.flagged_seen else []),
            )
        )
        return web.json_response({"status": "ok"})

    async def _api_mailbox(self, request: Request) -> Response:
        try:
            name = request.match_info["mailbox"]
            mailbox = await self.mailbox_set.get_mailbox(name)
        except KeyError as e:
            raise web.HTTPNotFound() from e

        result = []
        async for msg in mailbox.messages():
            result.append(await self._convert_message(msg))
        return web.json_response(result)

    async def _api_message(self, request: Request) -> Response:
        try:
            name = request.match_info["mailbox"]
            uid = int(request.match_info["uid"])
            mailbox = await self.mailbox_set.get_mailbox(name)
        except (IndexError, KeyError) as e:
            raise web.HTTPNotFound() from e

        async for msg in mailbox.messages():
            if msg.uid == uid:
                return web.json_response(await self._convert_message(msg, True))

        raise web.HTTPNotFound()

    async def _api_reply(self, request: Request) -> Response:
        try:
            name = request.match_info["mailbox"]
            uid = int(request.match_info["uid"])
            mailbox = await self.mailbox_set.get_mailbox(name)
        except (IndexError, KeyError) as e:
            raise web.HTTPNotFound() from e

        async for msg in mailbox.messages():
            if msg.uid == uid:
                message = await self._convert_message(msg, True)
                headers = message["header"]
                headers["subject"] = f"RE: {headers['subject']}"
                msg_id = headers.get("message-id", None)
                if msg_id:
                    headers["in-reply-to"] = msg_id
                    headers["references"] = f"{msg_id} {headers.get('references', '')}"
                headers["message-id"] = f"{uuid.uuid4()}@mail-devel"
                headers["to"] = headers["from"]
                headers["from"] = self.user
                headers.pop("content-type", None)
                for key in list(headers):
                    if key.startswith("x-"):
                        headers.pop(key, None)
                return web.json_response(message)

        raise web.HTTPNotFound()

    async def _api_attachment(self, request: Request) -> Response:
        try:
            name = request.match_info["mailbox"]
            uid = int(request.match_info["uid"])
            attachment = request.match_info["attachment"]
            mailbox = await self.mailbox_set.get_mailbox(name)
        except (IndexError, KeyError) as e:
            raise web.HTTPNotFound() from e

        message = None
        async for msg in mailbox.messages():
            if msg.uid == uid:
                content = content = bytes((await msg.load_content([])).content)
                message = message_from_bytes(content)

        if not message or not message.is_multipart():
            raise web.HTTPNotFound()

        for part in message.walk():
            if (
                part.get_content_disposition() == "attachment"
                and part.get_filename() == attachment
            ):
                body = part.get_payload(decode=part.get("Content-Transfer-Encoding"))
                return web.Response(
                    body=body.decode(),
                    headers={
                        "Content-Type": part.get("Content-Type"),
                        "Content-Disposition": part.get("Content-Disposition"),
                    },
                )

        raise web.HTTPNotFound()

    async def _api_flag(self, request: Request) -> Response:
        try:
            name = request.match_info["mailbox"]
            mailbox = await self.mailbox_set.get_mailbox(name)
            uid = int(request.match_info["uid"])

            if request.method in ("DELETE", "PUT"):
                flag = request.match_info["flag"].title()
                flag = Flag(b"\\" + flag.encode())
            else:
                flag = None
        except (IndexError, KeyError) as e:
            raise web.HTTPNotFound() from e

        async for msg in mailbox.messages():
            if msg.uid != uid:
                continue

            if request.method == "DELETE":
                msg.permanent_flags = msg.permanent_flags.difference([flag])
            elif request.method == "PUT":
                msg.permanent_flags = msg.permanent_flags.union([flag])

            return web.json_response(flags_to_api(msg.permanent_flags))

        raise web.HTTPNotFound()
