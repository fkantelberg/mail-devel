import asyncio
import logging
import signal
import sys
from argparse import Namespace
from contextlib import suppress

from pymap.parsing.specials.searchkey import SearchKey

from . import utils
from .service import Service

_logger = logging.getLogger(__name__)


# Manual patch for https://github.com/icgood/pymap/pull/138 for py3.10
if sys.version_info[:2] == (3, 10):
    original_func = SearchKey.__init__

    def patched_searchkey(self, key, filter_=None, inverse=False):
        if isinstance(filter_, list):
            filter_ = frozenset(filter_)
        return original_func(self, key, filter_, inverse)

    SearchKey.__init__ = patched_searchkey

# Manual patch for https://github.com/icgood/pymap/issues/158 for py3.11
if sys.version_info[:2] == (3, 11):
    original_func = SearchKey._get_filter

    def patched_get_filter(self, cls):
        if cls == frozenset:
            cls = tuple
        return original_func(self, cls)

    SearchKey._get_filter = patched_get_filter


async def sleep_forever() -> None:
    with suppress(asyncio.CancelledError):
        while True:
            await asyncio.sleep(60)


async def run(args: Namespace) -> None:
    loop = asyncio.get_event_loop()
    service = await Service.init(args)
    async with service.start():
        forever = asyncio.create_task(sleep_forever())
        loop.add_signal_handler(signal.SIGINT, forever.cancel)
        loop.add_signal_handler(signal.SIGTERM, forever.cancel)
        await forever


def main() -> None:
    args = Service.parse()

    utils.configure_logging(level="DEBUG" if args.debug else "INFO")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
