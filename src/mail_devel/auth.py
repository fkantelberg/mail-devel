import logging
from typing import Any

from aiosmtpd.smtp import SMTP, AuthResult, Envelope, LoginPassword, Session
from pymap.backend.dict import Config, Identity, Login
from pymap.user import UserMetadata
from pysasl.creds.plain import PlainCredentials
from pysasl.creds.server import ServerCredentials

_logger = logging.getLogger(__name__)


def ensure_bytes(x: bytes | str) -> bytes:
    return x.encode() if isinstance(x, str) else x


class IMAPAuthenticator(Login):
    def __init__(self, config: Config, multi_user: bool = False) -> None:
        super().__init__(config)
        self.multi_user = multi_user

    async def authenticate(self, credentials: ServerCredentials) -> Identity:
        authcid = credentials.authcid

        if authcid not in self.users_dict:
            self.users_dict[authcid] = UserMetadata(self.config, authcid)

        if self.multi_user and isinstance(credentials, PlainCredentials):
            credentials = PlainCredentials(self.config.demo_user, credentials._secret)

        ident = await super().authenticate(credentials)
        ident._name = authcid
        return ident


class SMTPAuthenticator:
    def __init__(self, user: str, password: str, multi_user: bool = False) -> None:
        self.user, self.password = map(ensure_bytes, (user, password))
        self.multi_user = multi_user

    def __call__(  # pylint: disable=R0917
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

        if self.password != auth_data.password:
            return AuthResult(success=False, handled=False)

        if not self.multi_user and self.user != auth_data.login:
            return AuthResult(success=False, handled=False)

        return AuthResult(success=True)
