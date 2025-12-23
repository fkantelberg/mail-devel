import os

from mail_devel.builder import Builder
from mail_devel.smtp import Logger, Message, Reply, Response
from mail_devel.utils import str2bool


def reply(message: Message, flags: set[str], _logger: Logger) -> Response:
    yield Reply(
        Builder.reply_mail(
            message,
            use_reply_to=str2bool(os.environ.get("MAIL_USE_REPLY_TO", "")),
        ),
        flags - {"Seen"},
    )
