"""F1: get jobs (alert emails or the Naukri scraper) -> prefilter -> dedupe -> insert. Never fails silently."""
from dataclasses import dataclass, field
from datetime import timedelta

from jobagent.core.db import Database
from jobagent.core.logging import get_logger
from jobagent.core.mail import MailAuthError, MailSource
from jobagent.core.notify import Notifier
from jobagent.core.schemas import JobRaw
from jobagent.flows.f0_profile.prefs import SearchPrefs
from jobagent.flows.f1_discovery.gmail_source import GMAIL_QUERY, ParserError, parser_for
from jobagent.flows.f1_discovery.normalizer import canonical_url, dedupe_key
from jobagent.flows.f1_discovery.prefilter import passes
from jobagent.flows.f1_discovery.scraper_source import NaukriScraperSource

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
    # scraper source only
    scraped: int = 0
    expired: int = 0
    scrape_errors: int = 0


class Ingest:
    """Shared by every source: filter -> dedupe -> insert. Holds the within-batch dedupe sets."""

    def __init__(self, db: Database, prefs: SearchPrefs, res: DiscoveryResult):
        self.db, self.prefs, self.res = db, prefs, res
        self.seen_keys: set[str] = set()
        self.seen_urls: set[str] = set()

    def add(self, job: JobRaw) -> None:
        db, res = self.db, self.res
        keep, reason, flags = passes(job, self.prefs, db.now())
        if not keep:
            res.rejected += 1
            res.reject_reasons.append(f"{job.title}: {reason}")
            return
        url, key = canonical_url(job.url), dedupe_key(job)
        if key in self.seen_keys or url in self.seen_urls or db.one(
                "SELECT 1 FROM jobs WHERE dedupe_key=? OR canonical_url=?", (key, url)):
            res.duplicates += 1
            return
        self.seen_keys.add(key)
        self.seen_urls.add(url)
        cur = db.write(
            "INSERT INTO jobs(dedupe_key, canonical_url, source, title, company, location, posted_at, discovered_at,"
            " snippet, jd_raw, apply_url, status, status_updated_at, flags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, url, job.source, job.title, job.company, job.location,
             job.posted_at.isoformat(timespec="seconds") if job.posted_at else None, db.now_iso(),
             job.snippet, job.jd_text, job.url, "DISCOVERED", db.now_iso(), ",".join(flags)))
        res.inserted += 1
        if cur.lastrowid:
            db.write("INSERT INTO job_history(job_id, from_status, to_status, note, at) VALUES (?,?,?,?,?)",
                     (cur.lastrowid, None, "DISCOVERED", f"from {job.source}", db.now_iso()))


def run_discovery(db: Database, mail: MailSource, prefs: SearchPrefs, notifier: Notifier) -> DiscoveryResult:
    """Source 1: LinkedIn / Naukri alert emails."""
    res = DiscoveryResult()
    now = db.now()
    try:
        emails = mail.search(GMAIL_QUERY, now - timedelta(days=prefs.max_age_days))
    except MailAuthError as e:
        res.auth_failed = True
        log.error("Gmail auth failed: %s", e)
        notifier.alert("auth_failed", f"Gmail auth failed ({e}). Job discovery did not run - re-authorise Gmail.")
        return res

    ingest = Ingest(db, prefs, res)
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
            ingest.add(job)
        db.write("INSERT OR IGNORE INTO processed_emails(email_id, kind, processed_at) VALUES (?,?,?)",
                 (email.id, "job_alert", db.now_iso()))

    log.info("discovery: %s", res)
    if res.inserted == 0 and not res.parser_errors:
        notifier.alert("zero_jobs", f"0 jobs discovered today ({res.emails} new emails, {res.rejected} filtered, {res.duplicates} duplicates).")
    return res


def run_scraper_discovery(db: Database, source: NaukriScraperSource, prefs: SearchPrefs, notifier: Notifier) -> DiscoveryResult:
    """Source 2: Naukri job links scraped with a real browser. The full job description is stored with the job."""
    res = DiscoveryResult()
    try:
        batch = source.fetch(db.now())
    except Exception as e:  # browser could not start, etc.
        log.error("scraper failed: %s", e)
        notifier.alert("source_failed", f"Naukri scraper failed to run: {str(e)[:150]}")
        res.scrape_errors = 1
        return res
    res.scraped, res.expired, res.scrape_errors, res.parsed = batch.total, batch.expired, batch.errors, len(batch.jobs)
    ingest = Ingest(db, prefs, res)
    for job in batch.jobs:
        ingest.add(job)

    log.info("scraper discovery: %s", res)
    if batch.total and batch.errors == batch.total:  # every link failed: blocked, offline or markup changed
        notifier.alert("source_failed", f"Naukri scraper: all {batch.total} links failed (e.g. {batch.first_error}). Blocked or offline?")
    elif batch.total == 0:
        notifier.alert("zero_jobs", "Naukri scraper: no links to scrape.")
    elif res.inserted == 0:
        notifier.alert("zero_jobs", f"0 new jobs from {batch.total} Naukri links ({res.rejected} filtered, {res.duplicates} duplicates, "
                                    f"{batch.expired} expired, {batch.errors} errors).")
    return res
