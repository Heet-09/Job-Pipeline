"""Logging with secret redaction (SAF-05): passwords, tokens and CTC never reach a log in plain text."""
import logging
import re

_PATTERNS = [
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|token)\b(\W{0,4})([^\s,;&\"']+)"), r"\1\2***"),
    (re.compile(r"(?i)(bearer)\s+[A-Za-z0-9._\-]+"), r"\1 ***"),
    (re.compile(r"\b(?:sk|gsk|ghp)[-_][A-Za-z0-9_\-]{10,}"), "***"),
    (re.compile(r"(?i)\b((?:current|expected|present)[ _]?(?:ctc|salary|compensation)|ctc)\b(\W{0,6})[\d][\d.,]*(\s*(?:lpa|lakhs?|lacs?|k|cr)?)"), r"\1\2[REDACTED]"),
]
_secrets: set[str] = set()


def register_secret(value) -> None:
    """Register an exact value (e.g. the user's CTC) that must be masked wherever it appears."""
    s = str(value).strip()
    if len(s) >= 3:
        _secrets.add(s)


def clear_secrets() -> None:
    _secrets.clear()


def redact(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    for s in _secrets:
        text = text.replace(s, "***")
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def get_logger(name: str = "jobagent") -> logging.Logger:
    log = logging.getLogger(name)
    root = logging.getLogger("jobagent")
    if not any(isinstance(f, RedactingFilter) for f in root.filters):
        root.addFilter(RedactingFilter())
    return log


def setup_logging(logfile: str | None = None, level=logging.INFO) -> None:
    root = logging.getLogger("jobagent")
    root.setLevel(level)
    handler = logging.FileHandler(logfile, encoding="utf-8") if logfile else logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
