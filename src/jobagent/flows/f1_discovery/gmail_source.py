"""Alert-email parsers (one class per source) and the sender -> parser routing."""
import re
from datetime import datetime

from bs4 import BeautifulSoup

from jobagent.core.mail import Email
from jobagent.core.schemas import JobRaw
from jobagent.flows.f1_discovery.normalizer import parse_posted

GMAIL_QUERY = "from:(jobalerts-noreply@linkedin.com OR naukri.com) newer_than:3d"


class ParserError(Exception):
    """The email looked like a job alert but no job could be parsed (template probably changed)."""


def _lines(container, skip: str) -> list[str]:
    lines = [ln.strip() for ln in container.get_text("\n").split("\n") if ln.strip()]
    return [ln for ln in lines if ln != skip]


class LinkedInAlertParser:
    source = "linkedin_alert"

    def parse(self, email: Email) -> list[JobRaw]:
        soup = BeautifulSoup(email.html, "html.parser")
        jobs = []
        for a in soup.select('a[href*="/jobs/view/"]'):
            title = a.get_text(" ", strip=True)
            if not title:
                continue
            box = a.find_parent(["td", "li", "div"]) or a.parent
            lines = _lines(box, title)
            if not lines:
                continue
            company, _, location = (p.strip() for p in lines[0].partition("·"))
            posted = next((parse_posted(ln, email.received_at) for ln in lines if re.search(r"ago|today|just now", ln, re.I)), None)
            jobs.append(JobRaw(url=a["href"], source=self.source, title=title, company=company,
                               location=location or None, posted_at=posted, snippet=" | ".join(lines)[:500]))
        if not jobs:
            raise ParserError(f"LinkedIn alert {email.id!r}: no jobs found - template may have changed")
        return jobs


class NaukriAlertParser:
    source = "naukri_alert"

    def parse(self, email: Email) -> list[JobRaw]:
        soup = BeautifulSoup(email.html, "html.parser")
        jobs = []
        for a in soup.select('a[href*="naukri.com/job-listings"]'):
            title = a.get_text(" ", strip=True)
            if not title:
                continue
            box = a.find_parent(["td", "li", "div"]) or a.parent
            company = (box.select_one(".comp") or box.select_one(".company"))
            loc = box.select_one(".loc")
            exp = box.select_one(".exp")
            posted_el = box.select_one(".posted")
            if not company:
                continue
            jobs.append(JobRaw(
                url=a["href"], source=self.source, title=title, company=company.get_text(strip=True),
                location=loc.get_text(strip=True) if loc else None,
                exp_text=exp.get_text(strip=True).removeprefix("Exp:").strip() if exp else None,
                posted_at=parse_posted(posted_el.get_text(strip=True), email.received_at) if posted_el else None,
                snippet=" | ".join(_lines(box, title))[:500]))
        if not jobs:
            raise ParserError(f"Naukri alert {email.id!r}: no jobs found - template may have changed")
        return jobs


def parser_for(email: Email):
    d = email.sender_domain
    if "linkedin.com" in d:
        return LinkedInAlertParser()
    if "naukri.com" in d:
        return NaukriAlertParser()
    return None
