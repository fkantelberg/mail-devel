import argparse
import asyncio
import logging
import os
import secrets
import ssl
from contextlib import AsyncExitStack, asynccontextmanager
from typing import AsyncGenerator

from aiosmtpd.controller import Controller
from pymap.backend.dict import Config, DictBackend
from pymap.backend.dict.filter import FilterSet
from pymap.imap import IMAPService

from . import utils
from .auth import IMAPAuthenticator, SMTPAuthenticator
from .http import Frontend
from .mailbox import TestMailboxDict
from .smtp import MemoryHandler

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self

_logger = logging.getLogger(__name__)


async def imap_context(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        demo_data=False,
        demo_user=args.user,
        demo_password=args.password,
        host=args.imap_host or args.host,
        port=args.imap_port,
        debug=args.debug,
        cert=args.cert,
        key=args.key,
        passlib_cfg=None,
        tls=False,
        proxy_protocol=None,
        inherited_sockets=None,
    )


class Service:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args: argparse.Namespace = args
        self.imap: IMAPService | None = None
        self.login: IMAPAuthenticator | None = None
        self.smtp: Controller | None = None
        self.smtps: Controller | None = None
        self.frontend: Frontend | None = None
        self.backend: DictBackend | None = None
        self.config: Config | None = None
        self.handler: MemoryHandler | None = None
        self.mailboxes: TestMailboxDict | None = None
        self.filter_set: FilterSet | None = None
        self.ssl_context: ssl.SSLContext | None = None

    @property
    def demo_user(self) -> str | None:
        return self.config.demo_user if self.config else None

    def log_connection_info(self) -> None:
        tls = bool(self.args.cert and self.args.key)
        if self.args.http:
            _logger.info(f"HTTP service [{self.args.http_port}]")

        _logger.info(f"IMAP service [{self.args.imap_port}]")
        if tls:
            _logger.info(f"IMAP/STARTTLS service [{self.args.imap_port}]")

        if not self.args.starttls_required:
            _logger.info(f"SMTP service [{self.args.smtp_port}]")
        if tls:
            _logger.info(f"SMTP/STARTTLS service [{self.args.smtp_port}]")
            _logger.info(f"SMTPS service [{self.args.smtps_port}]")

    @classmethod
    async def init(cls, args: argparse.Namespace) -> Self:
        service = cls(args)

        if args.cert and args.key:
            service.ssl_context = utils.generate_ssl_context(
                cert=args.cert, key=args.key
            )

        # Create the IMAP and optionally IMAPS service
        service.filter_set = FilterSet()
        backend_args = await imap_context(args)

        service.config = Config.from_args(backend_args)
        service.login = IMAPAuthenticator(service.config, args.multi_user)
        await DictBackend._add_demo_user(service.config, service.login)
        service.backend = DictBackend(service.login, service.config)

        service.mailboxes = TestMailboxDict(
            service.config, service.filter_set, args.multi_user
        )
        service.imap = IMAPService(service.backend, service.config)

        # Create the SMTP and optionally SMTPS service
        service.handler = MemoryHandler(
            service.mailboxes,
            flagged_seen=args.flagged_seen or args.smtp_flagged_seen,
            ensure_message_id=not args.no_message_id or not args.smtp_no_message_id,
            multi_user=args.multi_user,
            responder=args.smtp_responder,
        )
        service.smtp = Controller(
            service.handler,
            hostname=args.smtp_host or args.host,
            port=args.smtp_port,
            tls_context=service.ssl_context,
            auth_required=args.auth_required,
            auth_require_tls=args.auth_require_tls,
            require_starttls=args.starttls_required,
            enable_SMTPUTF8=True,
            authenticator=SMTPAuthenticator(
                args.user,
                args.password,
                args.multi_user,
            ),
        )

        if service.ssl_context:
            service.smtps = Controller(
                service.handler,
                hostname=args.smtp_host or args.host,
                port=args.smtps_port,
                ssl_context=service.ssl_context,
                auth_required=args.auth_required,
                auth_require_tls=args.auth_require_tls,
                enable_SMTPUTF8=True,
                authenticator=SMTPAuthenticator(
                    args.user,
                    args.password,
                    args.multi_user,
                ),
            )

        # Create the HTTP service
        if args.http:
            service.frontend = Frontend(
                service.mailboxes,
                user=args.user,
                host=args.http_host or args.host,
                port=args.http_port,
                devel=args.devel,
                flagged_seen=args.flagged_seen or args.http_flagged_seen,
                ensure_message_id=not args.no_message_id or not args.http_no_message_id,
                client_max_size=args.client_max_size,
                multi_user=args.multi_user,
            )

        return service

    @asynccontextmanager
    async def start(self) -> AsyncGenerator[None, None]:
        loop = asyncio.get_event_loop()
        if self.frontend:
            loop.create_task(self.frontend.start())

        async with AsyncExitStack() as stack:
            if self.backend:
                await self.backend.start(stack)
            if self.imap:
                await self.imap.start(stack)
            if self.smtp:
                self.smtp.start()
            if self.smtps:
                self.smtps.start()

            self.log_connection_info()
            yield

    @classmethod
    def parse(cls, args: list[str] | None = None) -> argparse.Namespace:
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--host",
            default=os.environ.get("MAIL_HOST", ""),
            help="The IP to bind the listening server ports. Can also be set using "
            "the environment variable MAIL_HOST. Default is %(default)s",
        )
        parser.add_argument(
            "--user",
            default=os.environ.get("MAIL_USER", "test@example.org"),
            help="The user account for SMTP and IMAP. Can also be set using "
            "the environment variable MAIL_USER. Default is %(default)s",
        )
        parser.add_argument(
            "--multi-user",
            action="store_true",
            help="Switches from the single mailbox to multi mailbox mode. The "
            "password will be reused for every mailbox",
        )
        pw = parser.add_argument(
            "--password",
            default=os.environ.get("MAIL_PASSWORD"),
            help="The password for SMTP and IMAP. Can also be set using the "
            "environment variable MAIL_PASSWORD",
        )
        parser.add_argument(
            "--gen-password",
            default=False,
            action="store_true",
            help="Generate the SMTP and IMAP password and print at start",
        )

        group = parser.add_argument_group("IMAP")
        group.add_argument(
            "--imap-host",
            default=False,
            help="Overrules the IP binding specifically for IMAP",
        )
        group.add_argument(
            "--imap-port",
            metavar="PORT",
            default=int(os.environ.get("MAIL_IMAP_PORT", 4143)),
            help="The port of the IMAP interface. Can also be set using the "
            "environment variable MAIL_IMAP_PORT. Default is %(default)s",
        )

        group = parser.add_argument_group("HTTP")
        group.add_argument(
            "--http-host",
            default=False,
            help="Overrules the IP binding specifically for HTTP",
        )
        group.add_argument(
            "--http-port",
            metavar="PORT",
            default=int(os.environ.get("MAIL_HTTP_PORT", 4080)),
            help="The port of the HTTP interface. Can also be set using the "
            "environment variable MAIL_HTTP_PORT. Default is %(default)s",
        )
        group.add_argument(
            "--no-http",
            dest="http",
            action="store_false",
            help="Disable the HTTP server",
        )
        group.add_argument(
            "--client-max-size",
            default="1M",
            type=utils.convert_size,
            help="Max body size for POST requests",
        )
        group.add_argument(
            "--http-flagged-seen",
            action="store_true",
            help="Flag messages in the INBOX as seen if they arrive via HTTP",
        )
        group.add_argument(
            "--http-no-message-id",
            action="store_true",
            help="Ensure that a Message-ID exists via HTTP",
        )

        group = parser.add_argument_group("SMTP")
        group.add_argument(
            "--smtp-host",
            default=False,
            help="Overrules the IP binding specifically for smtp",
        )
        group.add_argument(
            "--smtp-port",
            metavar="PORT",
            default=int(os.environ.get("MAIL_SMTP_PORT", 4025)),
            help="The port of the SMTP interface. Can also be set using the "
            "environment variable MAIL_SMTP_PORT. Default is %(default)s",
        )
        group.add_argument(
            "--smtps-port",
            metavar="PORT",
            default=int(os.environ.get("MAIL_SMTPS_PORT", 4465)),
            help="The port of the SMTPS interface. Can also be set using the "
            "environment variable MAIL_SMTPS_PORT. Requires --cert and --key. "
            "Default is %(default)s",
        )
        group.add_argument(
            "--auth-required",
            action="store_true",
            help="Required SMTP AUTH",
        )
        group.add_argument(
            "--auth-require-tls",
            action="store_true",
            help="Require TLS for SMTP AUTH",
        )
        group.add_argument(
            "--starttls-required",
            action="store_true",
            help="Require STARTTLS",
        )
        group.add_argument(
            "--smtp-flagged-seen",
            action="store_true",
            help="Flag messages in the INBOX as seen if they arrive via SMTP",
        )
        group.add_argument(
            "--smtp-no-message-id",
            action="store_true",
            help="Ensure that a Message-ID exists via SMTP",
        )
        group.add_argument(
            "--smtp-responder",
            help="Automatically respond to received mails. Possible options are "
            "pre-defined scripts like reply_once or reply_always or a path to "
            "python script with the defined reply() function. See the source of the "
            "pre-defined scripts for the interface definition",
        )

        group = parser.add_argument_group("Options")
        group.add_argument("--debug", action="store_true", help="Verbose logging")
        group.add_argument(
            "--devel",
            type=lambda x: utils.valid_file(x, True),
            help="Use files from the working directory instead of the resources for "
            "the HTTP frontend. Useful for own frontends or development",
        )
        group.add_argument(
            "--flagged-seen",
            action="store_true",
            help="Flag messages in the INBOX as seen if they arrive via SMTP and HTTP",
        )
        group.add_argument(
            "--no-message-id",
            action="store_true",
            help="Ensure that a Message-ID exists via SMTP and HTTP",
        )

        group = parser.add_argument_group("Security")
        group.add_argument(
            "--cert",
            default=None,
            metavar="FILE",
            type=utils.valid_file,
            help="TLS certificate file",
        )
        group.add_argument(
            "--key",
            default=None,
            metavar="FILE",
            type=utils.valid_file,
            help="TLS key file",
        )

        parsed = parser.parse_args(args)
        if parsed.gen_password:
            parsed.password = secrets.token_hex(16)
        if not parsed.password:
            raise argparse.ArgumentError(pw, "Missing argument `password`")
        return parsed
