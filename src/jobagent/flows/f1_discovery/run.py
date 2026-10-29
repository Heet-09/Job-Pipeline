"""F1: fetch alert emails -> parse -> prefilter -> dedupe -> insert. Never fails silently."""
from dataclasses import dataclass, field
from datetime import timedelta

from jobagent.core.db import Database
from jobagent.core.logging import get_logger
from jobagent.core.mail import MailAuthError, MailSource
from jobagent.core.notify import Notifier
from jobagent.flows.f0_profile.prefs import SearchPrefs
from jobagent.flows.f1_discovery.gmail_source import GMAIL_QUERY, ParserError, parser_for
from jobagent.flows.f1_discovery.normalizer import canonical_url, dedupe_key
from jobagent.flows.f1_discovery.prefilter import passes

log = get_logger("jobagent.discovery")


@dataclass
class DiscoveryResult:
    emails: int = 0
    parsed: int = 0
    inserted: int = 0
    duplicates: int = 0
    rejected: int = 0
    parser_errors: int = 0
    auth_failed: bool = False
    reject_reasons: list[str] = field(default_factory=list)


def run_discovery(db: Database, mail: MailSource, prefs: SearchPrefs, notifier: Notifier) -> DiscoveryResult:
    res = DiscoveryResult()
    now = db.now()
    try:
        emails = mail.search(GMAIL_QUERY, now - timedelta(days=prefs.max_age_days))
    except MailAuthError as e:
        res.auth_failed = True
        log.error("Gmail auth failed: %s", e)
        notifier.alert("auth_failed", f"Gmail auth failed ({e}). Job discovery did not run - re-authorise Gmail.")
        return res

    seen_keys: set[str] = set()
    seen_urls: set[str] = set()
    for email in emails:
        if db.one("SELECT 1 FROM processed_emails WHERE email_id=?", (email.id,)):
            continue  # already handled on an earlier run
        res.emails += 1
        parser = parser_for(email)
        if parser is None:
            continue
        try:
            jobs = parser.parse(email)
        except ParserError as e:
            res.parser_errors += 1
            log.error("parser failed: %s", e)
            notifier.alert("parser_failed", str(e))
            continue  # leave unprocessed so it is retried after the parser is fixed
        res.parsed += len(jobs)
        for job in jobs:
            keep, reason, flags = passes(job, prefs, now)
            if not keep:
                res.rejected += 1
                res.reject_reasons.append(f"{job.title}: {reason}")
                continue
            url, key = canonical_url(job.url), dedupe_key(job)
            if key in seen_keys or url in seen_urls or db.one(
                    "SELECT 1 FROM jobs WHERE dedupe_key=? OR canonical_url=?", (key, url)):
                res.duplicates += 1
                continue
            seen_keys.add(key)
            seen_urls.add(url)
            db.write(
                "INSERT INTO jobs(dedupe_key, canonical_url, source, title, company, location, posted_at, discovered_at,"
                " snippet, apply_url, status, status_updated_at, flags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, url, job.source, job.title, job.company, job.location,
                 job.posted_at.isoformat(timespec="seconds") if job.posted_at else None, db.now_iso(),
                 job.snippet, job.url, "DISCOVERED", db.now_iso(), ",".join(flags)))
            res.inserted += 1
        db.write("INSERT OR IGNORE INTO processed_emails(email_id, kind, processed_at) VALUES (?,?,?)",
                 (email.id, "job_alert", db.now_iso()))

    log.info("discovery: %s", res)
    if res.inserted == 0 and not res.parser_errors:
        notifier.alert("zero_jobs", f"0 jobs discovered today ({res.emails} new emails, {res.rejected} filtered, {res.duplicates} duplicates).")
    return res
