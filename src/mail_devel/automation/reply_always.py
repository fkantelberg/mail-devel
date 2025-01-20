from mail_devel.builder import Builder
from mail_devel.smtp import Logger, Message, Reply, Response


def reply(message: Message, flags: set[str], _logger: Logger) -> Response:
    yield Reply(Builder.reply_mail(message), flags - {"Seen"})
