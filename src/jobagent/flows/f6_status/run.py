"""F6: fetch replies, match + classify, update status, alert on interviews, mark ghosted applications."""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from jobagent.core.config import Settings
from jobagent.core.db import Database
from jobagent.core.llm import LLMClient
from jobagent.core.logging import get_logger
from jobagent.core.mail import Email, MailAuthError, MailSource
from jobagent.core.notify import Notifier
from jobagent.flows.f6_status.classifier import classify, email_text
from jobagent.flows.f6_status.matcher import match

log = get_logger("jobagent.status")

OPEN = ("SUBMITTED", "RECEIVED", "SHORTLISTED", "INTERVIEW")
LABEL_TO_STATUS = {"received": "RECEIVED", "under_review": "RECEIVED", "shortlisted": "SHORTLISTED",
                   "interview_scheduled": "INTERVIEW", "rejected": "REJECTED"}
RANK = {"SUBMITTED": 0, "RECEIVED": 1, "SHORTLISTED": 2, "INTERVIEW": 3, "REJECTED": 4}
ALERT_SENDERS = ("linkedin.com", "naukri.com")
HINT = re.compile(r"application|applied|interview|candidate|candidacy|position|your profile|hiring|recruit", re.I)
NEWSLETTER = re.compile(r"newsletter|unsubscribe|weekly digest|% off|promo|webinar|sale\b", re.I)
GMAIL_QUERY = "newer_than:2d -from:(jobalerts-noreply@linkedin.com)"


@dataclass
class StatusSummary:
    fetched: int = 0
    updated: int = 0
    manual: int = 0
    ignored: int = 0
    interview_alerts: int = 0
    auth_failed: bool = False
    ghosted: int = 0
    details: list[str] = field(default_factory=list)


def _open_apps(db: Database) -> list[dict]:
    q = ",".join("?" * len(OPEN))
    return [dict(r) for r in db.query(
        f"""SELECT a.id AS application_id, a.current_status, j.company, j.title, j.id AS job_id FROM applications a
            JOIN jobs j ON j.id = a.job_id WHERE a.current_status IN ({q})""", OPEN)]


def _to_manual(db: Database, email: Email, reason: str) -> None:
    db.write("INSERT INTO manual_review(email_id, sender, subject, reason, created_at) VALUES (?,?,?,?,?)",
             (email.id, email.sender, email.subject, reason, db.now_iso()))


def _update(db: Database, app: dict, status: str, email: Email) -> bool:
    cur = db.scalar("SELECT current_status FROM applications WHERE id=?", (app["application_id"],))
    db.write("INSERT INTO status_events(application_id, status, email_id, snippet, at) VALUES (?,?,?,?,?)",
             (app["application_id"], status, email.id, email_text(email)[:200], db.now_iso()))
    if cur != "GHOSTED" and RANK.get(status, -1) <= RANK.get(cur, -1):
        return False  # never move an application backwards (e.g. 'received' after 'interview')
    db.write("UPDATE applications SET current_status=? WHERE id=?", (status, app["application_id"]))
    return True


def _interview_alert(db: Database, notifier: Notifier, app: dict, when: str | None) -> None:
    title = f"{app['title']} @ {app['company']}"
    if when:
        start = datetime.fromisoformat(when)
        suggestion = {"summary": f"Interview: {title}", "start": start.isoformat(timespec="minutes"),
                      "end": (start + timedelta(hours=1)).isoformat(timespec="minutes")}
        notifier.alert("interview", f"Interview invitation for {title} on {when}. Suggested calendar event added.", calendar_event=suggestion)
    else:  # no time in the email: alert, but never create an event with a blank time
        notifier.alert("interview", f"Interview invitation for {title}, but the email gives no date/time. Please check it and schedule manually.", calendar_event=None)


def run_status_check(db: Database, mail: MailSource, notifier: Notifier, settings: Settings, llm: LLMClient | None = None) -> StatusSummary:
    s = StatusSummary()
    now = db.now()
    try:
        emails = mail.search(GMAIL_QUERY, now - timedelta(hours=48))
    except MailAuthError as e:
        s.auth_failed = True
        notifier.alert("auth_failed", f"Gmail auth failed ({e}); status tracking did not run.")
        return s
    apps = _open_apps(db)
    for email in emails:
        if any(d in email.sender_domain for d in ALERT_SENDERS):
            continue
        if db.one("SELECT 1 FROM processed_emails WHERE email_id=? AND kind='status'", (email.id,)):
            continue
        s.fetched += 1
        text = email_text(email)
        m = match(email, apps, settings.match_min_score, settings.match_min_margin)
        klass = classify(email, llm)
        if m.app is None:
            if HINT.search(text) and not NEWSLETTER.search(text):
                _to_manual(db, email, m.reason)
                s.manual += 1
            else:
                s.ignored += 1  # newsletter / unrelated
        elif klass.label == "other":
            _to_manual(db, email, "status unclear (matched application, unrecognised content)")
            s.manual += 1
        else:
            if _update(db, m.app, LABEL_TO_STATUS[klass.label], email):
                s.updated += 1
            if klass.label == "interview_scheduled":
                _interview_alert(db, notifier, m.app, klass.interview_datetime)
                s.interview_alerts += 1
        db.write("INSERT OR IGNORE INTO processed_emails(email_id, kind, processed_at) VALUES (?,?,?)", (email.id, "status", db.now_iso()))
    for a in apps:
        db.write("UPDATE applications SET last_checked_at=? WHERE id=?", (db.now_iso(), a["application_id"]))
    s.ghosted = check_ghosted(db, settings)
    return s


def check_ghosted(db: Database, settings: Settings) -> int:
    """GHOSTED after ghost_after_days with no activity. Any reply (status event) resets the clock."""
    cutoff = (db.now() - timedelta(days=settings.ghost_after_days)).isoformat(timespec="seconds")
    n = 0
    for r in db.query("""SELECT a.id, a.submitted_at, (SELECT MAX(at) FROM status_events e WHERE e.application_id = a.id) AS last_event
                         FROM applications a WHERE a.current_status IN ('SUBMITTED', 'RECEIVED') AND a.submitted_at IS NOT NULL"""):
        last = max(x for x in (r["submitted_at"], r["last_event"]) if x)
        if last <= cutoff:
            db.write("UPDATE applications SET current_status='GHOSTED' WHERE id=?", (r["id"],))
            db.write("INSERT INTO status_events(application_id, status, email_id, snippet, at) VALUES (?,?,?,?,?)",
                     (r["id"], "GHOSTED", None, f"no reply for {settings.ghost_after_days}+ days", db.now_iso()))
            n += 1
    return n
