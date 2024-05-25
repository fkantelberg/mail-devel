import secrets
import uuid
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class Builder:
    """Helper class to generate mails and randomized values"""

    @staticmethod
    def message_id() -> str:
        return f"<{uuid.uuid4()}@mail-devel>"

    @staticmethod
    def mail_address() -> str:
        return f"{secrets.token_hex(8)}@mail-devel"

    @staticmethod
    def reply_mail(message: Message) -> Message:
        body = ""
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode()
        elif message.get_content_type() == "text/plain":
            body = message.get_payload(decode=True).decode()

        reply = MIMEMultipart()
        if body:
            body = "\n\n> " + body.replace("\n", "\n> ")

        reply.attach(MIMEText("Reply" + body))

        reply.add_header("Message-Id", Builder.message_id())
        msg_id = message["Message-Id"]
        if msg_id:
            reply.add_header("In-Reply-To", msg_id)
            reply.add_header("References", f"{msg_id} {message.get('References', '')}")

        reply.add_header("Subject", f"Re: {message['Subject']}")
        reply.add_header("To", message["From"])
        reply.add_header("From", Builder.mail_address())
        if message["CC"]:
            reply.add_header("CC", message["CC"])

        return reply
