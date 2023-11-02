import logging
from email.message import Message
from typing import Any, Type

from aiosmtpd.handlers import AsyncMessage
from aiosmtpd.smtp import SMTP, AuthResult, Envelope, LoginPassword, Session
from pymap.parsing.specials.flag import Flag

from .mailbox import TestMailboxDict

_logger = logging.getLogger(__name__)


def ensure_bytes(x: bytes | str) -> bytes:
    return x.encode() if isinstance(x, str) else x


class Authenticator:
    def __init__(self, user: str, password: str):
        self.user, self.password = map(ensure_bytes, (user, password))

    def __call__(
        self,
        server: SMTP,
        session: Session,
        envelope: Envelope,
        mechanism: str,
        auth_data: Any,
    ) -> AuthResult:
        if mechanism not in ("LOGIN", "PLAIN"):
            return AuthResult(success=False, handled=False)

        if not isinstance(auth_data, LoginPassword):
            return AuthResult(success=False, handled=False)

        if (self.user, self.password) != (auth_data.login, auth_data.password):
            return AuthResult(success=False, handled=False)

        return AuthResult(success=True)


class MemoryHandler(AsyncMessage):
    def __init__(
        self,
        mailboxes: TestMailboxDict,
        flagged_seen: bool = False,
        message_class: Type[Message] | None = None,
        multi_user: bool = False,
    ):
        super().__init__(message_class)
        self.mailboxes = mailboxes
        self.flagged_seen = flagged_seen
        self.multi_user = multi_user

    async def handle_message(self, message: Message) -> None:  # type: ignore
        _logger.info(f"Got message {message['From']} -> {message['To']}")
        await self.mailboxes.append(
            message,
            flags=frozenset({Flag(b"\\Seen")} if self.flagged_seen else []),
        )
