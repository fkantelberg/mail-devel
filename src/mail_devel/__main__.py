import asyncio
import logging
import signal
from argparse import Namespace
from contextlib import suppress

from . import VERSION, utils
from .service import Service

_logger = logging.getLogger(__name__)


async def sleep_forever() -> None:
    with suppress(asyncio.CancelledError):
        while True:
            await asyncio.sleep(60)


async def run(args: Namespace) -> None:
    _logger.info(f"Version: {VERSION}")
    loop = asyncio.get_event_loop()
    service = await Service.init(args)
    async with service.start():
        forever = asyncio.create_task(sleep_forever())
        loop.add_signal_handler(signal.SIGINT, forever.cancel)
        loop.add_signal_handler(signal.SIGTERM, forever.cancel)
        await forever


def main() -> None:
    args = Service.parse()

    utils.configure_logging("DEBUG" if args.debug else "INFO")
    if args.gen_password:
        _logger.info(f"Password: {args.password}")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
