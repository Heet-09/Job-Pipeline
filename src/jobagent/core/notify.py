from typing import Protocol

from jobagent.core.logging import get_logger

log = get_logger("jobagent.notify")


class Notifier(Protocol):
    def alert(self, kind: str, message: str, **payload) -> None: ...


class LogNotifier:
    """Default: alerts go to the log. Swap for Telegram/email later."""

    def alert(self, kind: str, message: str, **payload) -> None:
        log.warning("ALERT[%s] %s", kind, message)


class MemoryNotifier:
    def __init__(self):
        self.alerts: list[dict] = []

    def alert(self, kind: str, message: str, **payload) -> None:
        self.alerts.append({"kind": kind, "message": message, **payload})
        log.warning("ALERT[%s] %s", kind, message)

    def kinds(self) -> list[str]:
        return [a["kind"] for a in self.alerts]


class DigestChannel(Protocol):
    def send(self, subject: str, body: str) -> None: ...


class MemoryChannel:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, subject: str, body: str) -> None:
        self.sent.append((subject, body))
