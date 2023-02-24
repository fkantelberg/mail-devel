import logging
from datetime import datetime
from email.message import Message
from typing import Any, Optional, Type, Union

from aiosmtpd.handlers import AsyncMessage
from aiosmtpd.smtp import SMTP, AuthResult, Envelope, LoginPassword, Session
from pymap.backend.dict import MailboxData
from pymap.parsing.message import AppendMessage
from pymap.parsing.specials.flag import Flag

_logger = logging.getLogger(__name__)


def ensure_bytes(x: Union[bytes, str]) -> bytes:
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
        mailbox: MailboxData,
        flagged_seen: bool = False,
        message_class: Optional[Type[Message]] = None,
    ):
        super().__init__(message_class)
        self.mailbox = mailbox
        self.flagged_seen = flagged_seen

    async def handle_message(self, message: Message) -> None:
        _logger.info(f"Got message {message['From']} -> {message['To']}")
        msg = AppendMessage(
            literal=str(message).encode(),
            when=datetime.now(),
            flag_set=frozenset({Flag(b"\\Seen")} if self.flagged_seen else []),
        )
        await self.mailbox.append(msg)
