"""Email -> label (+ interview time). Rules first; an optional small LLM only for what the rules cannot place."""
import re
from datetime import datetime

from dateutil import parser as dtparse

from jobagent.core.llm import LLMClient, LLMError
from jobagent.core.mail import Email
from jobagent.core.schemas import EmailClass
from jobagent.flows.f2_scoring.fetcher import html_to_text

REJECT = re.compile(r"regret to inform|unfortunately|not (be )?(moving|going) forward|will not be (moving|proceeding)|other candidates|not selected|decided (not )?to (proceed|move) with (other|another)|unable to (offer|proceed)", re.I)
INTERVIEW = re.compile(r"interview|schedule a (call|chat|discussion)|invite you to (a |an )?(call|chat|discussion|round)|technical round|screening call|book a slot", re.I)
SHORTLIST = re.compile(r"you(?:'ve| have)? been shortlisted|you are shortlisted|selected for the next|move forward with your (application|candidacy)|moving forward with your", re.I)
UNDER_REVIEW = re.compile(r"under review|reviewing your (application|profile)|currently reviewing|being reviewed", re.I)
RECEIVED = re.compile(r"received your application|thank you for (applying|your application|your interest)|application (was |has been |is )?(successfully )?(received|submitted)|we(?:'ve| have) received", re.I)

_TIME = r"(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)|\d{1,2}:\d{2})"
_DATES = [
    rf"(\d{{4}}-\d{{2}}-\d{{2}}[ T]{_TIME})",
    rf"(\d{{1,2}}(?:st|nd|rd|th)?\s+[A-Za-z]{{3,9}},?\s+\d{{4}}\s*(?:at|@|,|-)?\s*{_TIME})",
    rf"([A-Za-z]{{3,9}}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\s*(?:at|@|,|-)?\s*{_TIME})",
]


def extract_datetime(text: str) -> str | None:
    """Only returns a value when BOTH a date and a time are present (a calendar event needs a start time)."""
    for pat in _DATES:
        m = re.search(pat, text)
        if m:
            try:
                return dtparse.parse(re.sub(r"(\d)(st|nd|rd|th)", r"\1", m.group(1))).isoformat(timespec="minutes")
            except (ValueError, OverflowError):
                continue
    return None


def email_text(email: Email) -> str:
    return f"{email.subject}\n{email.text or html_to_text(email.html or '')}"


def classify(email: Email, llm: LLMClient | None = None) -> EmailClass:
    text = email_text(email)
    if REJECT.search(text):
        return EmailClass(label="rejected")
    if INTERVIEW.search(text):
        return EmailClass(label="interview_scheduled", interview_datetime=extract_datetime(text))
    if SHORTLIST.search(text):
        return EmailClass(label="shortlisted")
    if UNDER_REVIEW.search(text):
        return EmailClass(label="under_review")
    if RECEIVED.search(text):
        return EmailClass(label="received")
    if llm is not None:
        try:
            got = llm.call("small", "Classify this recruiting email. Reply JSON {\"label\": received|under_review|shortlisted|interview_scheduled|rejected|other, \"interview_datetime\": ISO or null}. Use 'other' when unsure.",
                           text[:3000], EmailClass, flow="classify_email")
            if got.label == "interview_scheduled" and not got.interview_datetime:
                got.interview_datetime = extract_datetime(text)
            return got
        except LLMError:
            pass
    return EmailClass(label="other")
