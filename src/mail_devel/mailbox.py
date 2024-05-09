import logging
from datetime import datetime
from email.message import Message
from email.utils import getaddresses

from pymap.backend.dict import FilterSet, MailboxData, MailboxSet
from pymap.imap import IMAPConfig
from pymap.parsing.message import AppendMessage
from pymap.parsing.specials.flag import Flag

_logger = logging.getLogger(__name__)


class TestMailboxSet(MailboxSet):
    """This MailboxSet creates the mailboxes automatically"""

    def __init__(self):
        super().__init__()
        self.mailbox_mapping: dict[int, str] = {}

    def id_of_mailbox(self, name: str) -> int:
        for mailbox_id, mailbox_name in self.mailbox_mapping.items():
            if mailbox_name == name:
                return mailbox_id

        new_id = len(self.mailbox_mapping) + 1
        self.mailbox_mapping[new_id] = name
        return new_id

    async def get_mailbox_by_id(self, mailbox_id: int) -> MailboxData:
        mailbox_name = self.mailbox_mapping[mailbox_id]
        return await self.get_mailbox(mailbox_name)

    def get_mailbox_name(self, mailbox_id: int) -> str:
        return self.mailbox_mapping[mailbox_id]

    async def get_mailbox(self, name: str) -> MailboxData:
        if name not in self._set:
            await self.add_mailbox(name)
        return await super().get_mailbox(name)


class TestMailboxDict:
    """Class to handle all mailbox accounts"""

    def __init__(
        self, config: IMAPConfig, filter_set: FilterSet, multi_user: bool = False
    ):
        self.config: IMAPConfig = config
        self.filter_set: FilterSet = filter_set
        self.multi_user: bool = multi_user
        self.user_mapping: dict[int, str] = {}

    def __contains__(self, user: str) -> bool:
        return not self.multi_user or user in self.config.set_cache

    def __getitem__(self, user: str) -> TestMailboxSet:
        return self.config.set_cache[user][0]

    def id_of_user(self, name: str) -> int:
        for uid, user_name in self.user_mapping.items():
            if user_name == name:
                return uid

        new_id = len(self.user_mapping) + 1
        self.user_mapping[new_id] = name
        return new_id

    async def inbox_stats(self) -> dict[str, int]:
        stats = {}
        for user, (mset, _fset) in self.config.set_cache.items():
            mbox = await mset.get_mailbox("INBOX")
            stats[user] = len([msg async for msg in mbox.messages()])
        return stats

    async def list(self):
        """List the available mailbox accounts"""
        if not self.config.set_cache:
            await self.get(self.config.demo_user)

        return list(self.config.set_cache)

    async def get_by_id(self, user_id: int) -> TestMailboxSet:
        if not self.multi_user:
            return await self.get(self.config.demo_user)

        user_name = self.user_mapping[user_id]
        return await self.get(user_name)

    async def get(self, user: str) -> TestMailboxSet:
        """Get the mailbox for the user or the main mailbox if single user mode"""
        if not self.multi_user:
            user = self.config.demo_user

        if user not in self.config.set_cache:
            mbox = TestMailboxSet()
            await mbox.get_mailbox("INBOX")
            self.config.set_cache[user] = mbox, self.filter_set
        return self.config.set_cache[user][0]

    async def append(
        self, message: Message, flags: frozenset[Flag], mailbox: str = "INBOX"
    ) -> None:
        """Push the message to the correct mailbox"""

        # Strip BCC header and collect the mail addresses
        addresses: set[str] = set()
        for header, value in list(message._headers):
            if value and header.lower() in ("to", "cc", "bcc"):
                addresses.update(x.strip() for x in value.split(","))

            if header.lower() == "bcc":
                message._headers.remove((header, value))

        append_msg = AppendMessage(
            literal=str(message).encode(),
            when=datetime.now(),
            flag_set=flags,
        )

        if not self.multi_user:
            account = await self.get(self.config.demo_user)
            mailboxset = await account.get_mailbox(mailbox)
            await mailboxset.append(append_msg)
            return

        for _, address in getaddresses(list(addresses)):
            if address:
                mailboxset = await self.get(address)
                mbox = await mailboxset.get_mailbox(mailbox)
                await mbox.append(append_msg)
