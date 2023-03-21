import argparse
import asyncio
import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager
from typing import List, TypeVar

from aiosmtpd.controller import Controller
from pymap.backend.dict import DictBackend, FilterSet
from pymap.imap import IMAPService

from . import utils
from .http import Frontend
from .mailbox import TestMailboxSet
from .smtp import Authenticator, MemoryHandler

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
        tls=False,
        proxy_protocol=None,
        inherited_sockets=None,
    )


class Service:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.imap = self.smtp = self.smtps = self.frontend = None
        self.backend = self.config = None
        self.handler = self.mailbox_set = self.filter_set = None
        self.ssl_context = None

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
    async def init(cls, args: argparse.Namespace) -> TypeVar("Service"):
        service = cls(args)

        if args.cert and args.key:
            service.ssl_context = utils.generate_ssl_context(
                cert=args.cert, key=args.key
            )

        # Create the mailbox
        service.mailbox_set = TestMailboxSet()
        service.filter_set = FilterSet()
        inbox = await service.mailbox_set.get_mailbox("INBOX")

        # Create the IMAP and optionally IMAPS service
        backend_args = await imap_context(args)
        service.backend, service.config = await DictBackend.init(backend_args)
        service.config.set_cache[args.user] = service.mailbox_set, service.filter_set
        service.imap = IMAPService(service.backend, service.config)

        # Create the SMTP and optionally SMTPS service
        service.handler = MemoryHandler(inbox, args.flagged_seen)
        service.smtp = Controller(
            service.handler,
            hostname=args.smtp_host or args.host,
            port=args.smtp_port,
            tls_context=service.ssl_context,
            auth_required=args.auth_required,
            auth_require_tls=args.auth_require_tls,
            require_starttls=args.starttls_required,
            authenticator=Authenticator(args.user, args.password),
        )

        if service.ssl_context:
            service.smtps = Controller(
                service.handler,
                hostname=args.smtp_host or args.host,
                port=args.smtps_port,
                ssl_context=service.ssl_context,
                auth_required=args.auth_required,
                auth_require_tls=args.auth_require_tls,
                authenticator=Authenticator(args.user, args.password),
            )

        # Create the HTTP service
        if args.http:
            service.frontend = Frontend(
                service.mailbox_set,
                host=args.http_host or args.host,
                port=args.http_port,
                devel=args.devel,
            )

        return service

    @asynccontextmanager
    async def start(self) -> None:
        async with AsyncExitStack() as stack:
            await self.backend.start(stack)
            await self.imap.start(stack)

            self.smtp.start()
            if self.smtps:
                self.smtps.start()

            if self.frontend:
                asyncio.create_task(self.frontend.start())

            self.log_connection_info()
            yield

    @classmethod
    def parse(cls, args: List[str] = None) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--host",
            default=os.environ.get("MAIL_HOST", ""),
            help="The IP to bind the listening server ports. Default is %(default)s",
        )
        parser.add_argument(
            "--user",
            default=os.environ.get("MAIL_USER", "test@example.org"),
            help="The user account for SMTP and IMAP. Default is %(default)s",
        )
        pw = parser.add_argument(
            "--password",
            default=os.environ.get("MAIL_PASSWORD"),
            help="The password for SMTP and IMAP",
        )

        group = parser.add_argument_group("IMAP")
        parser.add_argument(
            "--imap-host",
            default=False,
            help="Overrules the IP binding specifically for IMAP",
        )
        group.add_argument(
            "--imap-port",
            metavar="PORT",
            default=4143,
            help="The port of the IMAP interface. Default is %(default)s",
        )

        group = parser.add_argument_group("HTTP")
        parser.add_argument(
            "--http-host",
            default=False,
            help="Overrules the IP binding specifically for HTTP",
        )
        group.add_argument(
            "--http-port",
            metavar="PORT",
            default=4080,
            help="The port of the HTTP interface. Default is %(default)s",
        )
        group.add_argument(
            "--no-http",
            dest="http",
            action="store_false",
            help="Disable the HTTP server",
        )

        group = parser.add_argument_group("SMTP")
        parser.add_argument(
            "--smtp-host",
            default=False,
            help="Overrules the IP binding specifically for smtp",
        )
        group.add_argument(
            "--smtp-port",
            metavar="PORT",
            default=4025,
            help="The port of the SMTP interface. Default is %(default)s",
        )
        group.add_argument(
            "--smtps-port",
            metavar="PORT",
            default=4465,
            help="The port of the SMTPS interface. Requires --cert and --key. "
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
            "--flagged-seen",
            action="store_true",
            help="Flag messages in the INBOX as seen if they arrive via SMTP",
        )

        group = parser.add_argument_group("Options")
        group.add_argument("--debug", action="store_true", help="Verbose logging")
        group.add_argument(
            "--devel",
            action="store_true",
            help="Use files from the working directory instead of the resources for "
            "the HTTP frontend. Useful for own frontends or development",
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

        args = parser.parse_args(args)
        if not args.password:
            raise argparse.ArgumentError(pw, "Missing argument `password`")
        return args