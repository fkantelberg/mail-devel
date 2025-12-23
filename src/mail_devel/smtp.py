import importlib
import importlib.util
import logging
import os
import re
from email.message import Message
from logging import Logger
from types import ModuleType
from typing import Callable, Iterable, Iterator, Type

from aiosmtpd.handlers import AsyncMessage
from aiosmtpd.smtp import Envelope, Session
from pymap.parsing.specials.flag import Flag

from .builder import Builder
from .mailbox import TestMailboxDict

_logger = logging.getLogger(__name__)
_reply_logger = logging.getLogger(f"{__name__}.reply")


class Reply:
    def __init__(self, message: Message, flags: set[str] | None = None) -> None:
        self.message = message
        self.flags = set(flags or [])

    @property
    def message_id(self) -> str | None:
        return self.message["Message-Id"]


__all__ = ["Flag", "Logger", "Message", "Reply"]
Response = Iterator[Reply]
Responder = Callable[[Message, set[str], logging.Logger], Response]


def dummy(_message: Message, _flags: set[str], _logger: logging.Logger) -> Response:  # type: ignore
    """No auto respond mail"""


class MemoryHandler(AsyncMessage):
    def __init__(
        self,
        mailboxes: TestMailboxDict,
        *,
        flagged_seen: bool = False,
        ensure_message_id: bool = True,
        message_class: Type[Message] | None = None,
        multi_user: bool = False,
        responder: str | None = None,
    ) -> None:
        super().__init__(message_class)
        self.mailboxes: TestMailboxDict = mailboxes
        self.flagged_seen: bool = flagged_seen
        self.ensure_message_id = ensure_message_id
        self.multi_user: bool = multi_user

        self.responder: Responder | None = None
        self.load_responder(responder)

    def _default_flags(self) -> set[str]:
        return {"Seen"} if self.flagged_seen else set()

    def _convert_flags(
        self, flags: Iterable[bytes | str | Flag] | None
    ) -> frozenset[Flag]:
        result = []
        for flag in flags or []:
            if isinstance(flag, str):
                result.append(Flag(b"\\" + flag.title().encode()))
            elif isinstance(flag, bytes):
                result.append(Flag(b"\\" + flag.title()))
            else:
                result.append(flag)
        return frozenset(result)

    def _load_responder_from_script(self, script: ModuleType) -> Responder | None:
        responder = getattr(script, "reply", None)
        return responder if callable(responder) else None

    def _load_responder_from_file(self, responder: str) -> Responder | None:
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

            reply = self._load_responder_from_script(script)
            if not reply:
                return None

            _logger.info(f"Loaded auto responder {responder}")
            return reply
        except ImportError:
            return None

    def _load_responder_from_module(self, responder: str) -> Responder | None:
        if not re.match(r"^[0-9a-zA-Z_]+$", responder):
            return None

        try:
            script = importlib.import_module(f".automation.{responder}", __package__)
            _logger.info(f"Loaded auto responder .automation.{responder}")
            reply = self._load_responder_from_script(script)
            if not reply:
                return None

            _logger.info(f"Loaded auto responder {responder}")
            return reply
        except ImportError:
            return None

    def load_responder(self, responder: str | None = None) -> None:
        if not responder:
            return

        for func in [
            self._load_responder_from_module,
            self._load_responder_from_file,
        ]:
            reply = func(responder)
            if reply:
                self.responder = reply
                break

    async def auto_respond(self, message: Message) -> None:
        """Auto responder when a new message arrives via smtp"""
        if not self.responder or not callable(self.responder):
            return

        for reply in self.responder(
            message,
            self._default_flags(),
            _reply_logger,
        ):
            if isinstance(reply, Reply) and reply.message:
                _logger.info(
                    f"Auto responded {message['Message-Id'] or 'n/a'} with "
                    f"{reply.message_id or 'n/a'}"
                )
                await self.mailboxes.append(
                    reply.message,
                    flags=self._convert_flags(reply.flags),
                )

    def prepare_message(self, session: Session, envelope: Envelope) -> Message:
        if envelope.smtp_utf8 and isinstance(envelope.content, (bytes, bytearray)):
            data = envelope.content
            try:
                envelope.content = data.decode()
            except UnicodeError:
                pass
        return super().prepare_message(session, envelope)

    async def handle_message(self, message: Message) -> None:
        if not message["Message-Id"] and self.ensure_message_id:
            message.add_header("Message-Id", Builder.message_id())

        _logger.info(
            f"Got message {message['Message-Id']}: {message['From']} -> {message['To']}"
        )
        await self.mailboxes.append(
            message,
            flags=self._convert_flags(self._default_flags()),
        )

        await self.auto_respond(message)
