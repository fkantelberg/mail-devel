from email.message import Message
from logging import Logger

from mail_devel.builder import Builder
from mail_devel.smtp import Reply


def reply(message: Message, flags: set[str], _logger: Logger) -> Reply | None:
    return Reply(Builder.reply_mail(message), flags - {"Seen"})
