from datetime import datetime
from pathlib import Path

from jobagent.core.mail import Email, MailAuthError, parse_eml

FIXTURES = Path(__file__).parent / "fixtures"
RECEIVED = datetime(2026, 10, 29, 6, 0, 0)


def load_eml(name: str) -> Email:
    return parse_eml((FIXTURES / "emails" / name).read_bytes(), email_id=name)


class FakeMail:
    def __init__(self, emails=(), error: Exception | None = None):
        self.emails, self.error, self.queries = list(emails), error, []

    def search(self, query, since):
        self.queries.append(query)
        if self.error:
            raise self.error
        return list(self.emails)


def _ago(d):
    return f"{d} day{'s' if d != 1 else ''} ago"


def naukri_email(jobs, email_id="nk-custom", received=RECEIVED):
    """jobs: (title, company, location, days_ago, exp_text, url_suffix)"""
    rows = ""
    for t, c, loc, d, exp, sfx in jobs:
        rows += (f'<tr><td><a href="https://www.naukri.com/job-listings-{sfx}?src=x">{t}</a><span class="comp">{c}</span>'
                 f'<span class="exp">Exp: {exp}</span><span class="loc">{loc}</span><span class="posted">{_ago(d)}</span></td></tr>')
    return Email(email_id, "Naukri <info@naukri.com>", "alert", received, html=f"<table>{rows}</table>")


def linkedin_email(jobs, email_id="li-custom", received=RECEIVED):
    """jobs: (title, company, location, days_ago, view_url)"""
    rows = ""
    for t, c, loc, d, url in jobs:
        rows += f'<tr><td><a href="{url}">{t}</a><p>{c} · {loc}</p><p>{_ago(d)}</p></td></tr>'
    return Email(email_id, "LinkedIn <jobalerts-noreply@linkedin.com>", "alert", received, html=f"<table>{rows}</table>")


__all__ = ["load_eml", "FakeMail", "naukri_email", "linkedin_email", "MailAuthError"]
