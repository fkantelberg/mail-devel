import logging

from pymap.backend.dict import MailboxData, MailboxSet

_logger = logging.getLogger(__name__)


class TestMailboxSet(MailboxSet):
    """This MailboxSet creates the mailboxes automatically"""

    async def get_mailbox(self, name: str) -> MailboxData:
        if name != "INBOX" and name not in self._set:
            await self.add_mailbox(name)
        return await super().get_mailbox(name)
