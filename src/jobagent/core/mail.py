"""Mail abstraction. The real Gmail client implements MailSource; tests use fixtures / fakes."""
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from typing import Protocol


class MailAuthError(Exception):
    """Gmail token expired/revoked (HTTP 401)."""


@dataclass
class Email:
    id: str
    sender: str
    subject: str
    received_at: datetime
    html: str = ""
    text: str = ""

    @property
    def sender_address(self) -> str:
        return parseaddr(self.sender)[1].lower()

    @property
    def sender_domain(self) -> str:
        return self.sender_address.split("@")[-1]


class MailSource(Protocol):
    def search(self, query: str, since: datetime) -> list[Email]: ...


def parse_eml(data: bytes, email_id: str | None = None) -> Email:
    msg = BytesParser(policy=policy.default).parsebytes(data)
    html_part = msg.get_body(preferencelist=("html",))
    text_part = msg.get_body(preferencelist=("plain",))
    when = parsedate_to_datetime(msg["Date"]) if msg["Date"] else datetime.now()
    return Email(
        id=email_id or str(msg["Message-ID"] or msg["Subject"]),
        sender=str(msg["From"] or ""), subject=str(msg["Subject"] or ""),
        received_at=when.replace(tzinfo=None),
        html=html_part.get_content() if html_part else "",
        text=text_part.get_content() if text_part else "",
    )
