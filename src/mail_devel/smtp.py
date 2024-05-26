import importlib
import importlib.util
import logging
import os
from email.message import Message
from types import ModuleType
from typing import Callable, Iterable, Type

from aiosmtpd.handlers import AsyncMessage
from pymap.parsing.specials.flag import Flag

from .builder import Builder
from .mailbox import TestMailboxDict

_logger = logging.getLogger(__name__)
_reply_logger = logging.getLogger(f"{__name__}.reply")

Flags = frozenset[Flag]


class Reply:
    def __init__(self, message: Message, flags: set[str] | None = None):
        self.message = message
        self.flags = set(flags or [])


class MemoryHandler(AsyncMessage):
    def __init__(
        self,
        mailboxes: TestMailboxDict,
        flagged_seen: bool = False,
        ensure_message_id: bool = True,
        message_class: Type[Message] | None = None,
        multi_user: bool = False,
        responder: str | None = None,
    ):
        super().__init__(message_class)
        self.mailboxes: TestMailboxDict = mailboxes
        self.flagged_seen: bool = flagged_seen
        self.ensure_message_id = ensure_message_id
        self.multi_user: bool = multi_user

        self.responder: Callable | None = None
        self.load_responder(responder)

    def _default_flags(self) -> set[str]:
        return {"Seen"} if self.flagged_seen else set()

    def _convert_flags(
        self, flags: Flags | Iterable[bytes | str | Flag] | None
    ) -> Flags:
        result = []
        for flag in flags or []:
            if isinstance(flag, str):
                result.append(Flag(b"\\" + flag.title().encode()))
            elif isinstance(flag, bytes):
                result.append(Flag(b"\\" + flag.title()))
            else:
                result.append(flag)
        return frozenset(result)

    def _load_responder_from_file(self, responder: str) -> ModuleType | None:
        if not os.path.isfile(responder):
            return None

        try:
            spec = importlib.util.spec_from_file_location("autorespond", responder)
            if not spec or not spec.loader:
                return None

            script = importlib.util.module_from_spec(spec)
            if not script:
                return None

            spec.loader.exec_module(script)
            return script
        except ImportError:
            return None

    def load_responder(self, responder: str | None = None) -> None:
        if not responder:
            return

        try:
            script = importlib.import_module(f".automation.{responder}", __package__)
            _logger.info(f"Loaded auto responder .automation.{responder}")
        except ImportError:
            script = None

        if not script:
            script = self._load_responder_from_file(responder)
            if script:
                _logger.info(f"Loaded auto responder {responder}")

        if script:
            reply = getattr(script, "reply", None)
            if callable(reply):
                self.responder = reply

    async def auto_respond(self, message: Message) -> None:
        if not callable(self.responder):
            return

        reply = self.responder(
            message=message,
            flags=self._default_flags(),
            _logger=_reply_logger,
        )
        if isinstance(reply, Reply) and reply.message:
            await self.mailboxes.append(
                reply.message,
                flags=self._convert_flags(reply.flags),
            )

    def prepare_message(self, session, envelope):
        if envelope.smtp_utf8 and isinstance(envelope.content, (bytes, bytearray)):
            data = envelope.content
            try:
                envelope.content = data.decode()
            except UnicodeError:
                pass
        return super().prepare_message(session, envelope)

    async def handle_message(self, message: Message) -> None:  # type: ignore
        _logger.info(f"Got message {message['From']} -> {message['To']}")
        if not message["Message-Id"] and self.ensure_message_id:
            message.add_header("Message-Id", Builder.message_id())

        await self.mailboxes.append(
            message,
            flags=self._convert_flags(self._default_flags()),
        )

        await self.auto_respond(message)
