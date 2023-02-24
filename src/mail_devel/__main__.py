import argparse
import asyncio
import logging
import os
import signal
from argparse import Namespace
from contextlib import AsyncExitStack, suppress

from aiosmtpd.controller import Controller
from pymap.backend.dict import DictBackend, FilterSet
from pymap.imap import IMAPService
from pymap.parsing.specials.searchkey import SearchKey

from . import utils
from .http import Frontend
from .mailbox import TestMailboxSet
from .smtp import Authenticator, MemoryHandler

_logger = logging.getLogger(__name__)


# Manual patch for https://github.com/icgood/pymap/pull/138
original_func = SearchKey.__init__


def patched_searchkey(self, key, filter_=None, inverse=False):
    if isinstance(filter_, list):
        filter_ = frozenset(filter_)
    return original_func(self, key, filter_, inverse)


SearchKey.__init__ = patched_searchkey


async def sleep_forever() -> None:
    with suppress(asyncio.CancelledError):
        while True:
            await asyncio.sleep(60)


async def imap_context(args: Namespace) -> Namespace:
    return Namespace(
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


def log_connection_info(args: Namespace) -> None:
    tls = bool(args.cert and args.key)
    if args.http:
        _logger.info(f"HTTP service [{args.http_port}]")

    _logger.info(f"IMAP service [{args.imap_port}]")
    if tls:
        _logger.info(f"IMAP/STARTTLS service [{args.imap_port}]")

    if not args.starttls_required:
        _logger.info(f"SMTP service [{args.smtp_port}]")
    if tls:
        _logger.info(f"SMTP/STARTTLS service [{args.smtp_port}]")
        _logger.info(f"SMTPS service [{args.smtps_port}]")


async def run(args: Namespace) -> None:
    loop = asyncio.get_running_loop()

    if args.cert and args.key:
        ssl_context = utils.generate_ssl_context(cert=args.cert, key=args.key)
    else:
        ssl_context = None

    # Create the mailbox
    mailbox_set = TestMailboxSet()
    filter_set = FilterSet()
    inbox = await mailbox_set.get_mailbox("INBOX")

    # Create the IMAP and optionally IMAPS service
    backend_args = await imap_context(args)
    backend, config = await DictBackend.init(backend_args)
    config.set_cache[args.user] = mailbox_set, filter_set
    imap = IMAPService(backend, config)

    # Create the SMTP and optionally SMTPS service
    handler = MemoryHandler(inbox, args.flagged_seen)
    smtp = Controller(
        handler,
        hostname=args.smtp_host or args.host,
        port=args.smtp_port,
        tls_context=ssl_context,
        auth_required=args.auth_required,
        auth_require_tls=args.auth_require_tls,
        require_starttls=args.starttls_required,
        authenticator=Authenticator(args.user, args.password),
    )

    if ssl_context:
        smtps = Controller(
            handler,
            hostname=args.smtp_host or args.host,
            port=args.smtps_port,
            ssl_context=ssl_context,
            auth_required=args.auth_required,
            auth_require_tls=args.auth_require_tls,
            authenticator=Authenticator(args.user, args.password),
        )
    else:
        smtps = None

    # Create the HTTP service
    if args.http:
        frontend = Frontend(
            mailbox_set,
            host=args.http_host or args.host,
            port=args.http_port,
            devel=args.devel,
        )
    else:
        frontend = None

    # Start the services
    async with AsyncExitStack() as stack:
        await backend.start(stack)
        await imap.start(stack)

        smtp.start()
        if smtps:
            smtps.start()

        if frontend:
            asyncio.create_task(frontend.start())

        log_connection_info(args)

        forever = asyncio.create_task(sleep_forever())
        loop.add_signal_handler(signal.SIGINT, forever.cancel)
        loop.add_signal_handler(signal.SIGTERM, forever.cancel)
        await forever


def main() -> None:
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
    args = parser.parse_args()

    if not args.password:
        raise argparse.ArgumentError(pw, "Missing argument `password`")

    utils.configure_logging(level="DEBUG" if args.debug else "INFO")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
