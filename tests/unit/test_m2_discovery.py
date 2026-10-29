"""Module 2: DIS-01 .. DIS-05 (TC-006, TC-010 .. TC-025)."""
from datetime import timedelta

import pytest

from conftest import NOW
from helpers import FakeMail, MailAuthError, linkedin_email, load_eml, naukri_email
from jobagent.core.schemas import JobRaw
from jobagent.flows.f0_profile.prefs import SearchPrefs
from jobagent.flows.f1_discovery.gmail_source import LinkedInAlertParser, NaukriAlertParser
from jobagent.flows.f1_discovery.normalizer import canonical_url, dedupe_key
from jobagent.flows.f1_discovery.prefilter import passes
from jobagent.flows.f1_discovery.run import run_discovery

PREFS = SearchPrefs()


def job(title="GenAI Engineer", company="Acme", location="Mumbai", days=1, **kw):
    return JobRaw(url="https://x/1", source="t", title=title, company=company, location=location,
                  posted_at=None if days is None else NOW - timedelta(days=days), **kw)


# ---------------- DIS-01 ----------------
def test_tc010_five_linkedin_alert_emails_parse_all_jobs():
    total = 0
    for i in range(1, 6):
        jobs = LinkedInAlertParser().parse(load_eml(f"linkedin_{i}.eml"))
        assert len(jobs) == 3
        for j in jobs:
            assert j.title and j.company and j.url.startswith("https://www.linkedin.com/comm/jobs/view/")
            assert j.posted_at is not None
        total += len(jobs)
    assert total == 15


def test_tc011_five_naukri_alert_emails_parse_all_jobs():
    total = 0
    for i in range(1, 6):
        jobs = NaukriAlertParser().parse(load_eml(f"naukri_{i}.eml"))
        assert len(jobs) == 3
        for j in jobs:
            assert j.title and j.company and "naukri.com/job-listings" in j.url
            assert j.exp_text == "1-4 Yrs"
        total += len(jobs)
    assert total == 15


def test_tc012_same_email_processed_twice_inserts_no_duplicates(db, notifier):
    mail = FakeMail([load_eml("linkedin_1.eml")])
    first = run_discovery(db, mail, PREFS, notifier)
    count = db.scalar("SELECT COUNT(*) FROM jobs")
    second = run_discovery(db, mail, PREFS, notifier)
    assert first.inserted == 3 and count == 3
    assert second.inserted == 0 and db.scalar("SELECT COUNT(*) FROM jobs") == 3
    assert db.scalar("SELECT COUNT(*) FROM processed_emails") == 1


def test_tc013_changed_template_logs_error_alerts_and_does_not_crash(db, notifier, caplog):
    mail = FakeMail([load_eml("linkedin_changed_template.eml"), load_eml("naukri_1.eml")])
    with caplog.at_level("ERROR"):
        res = run_discovery(db, mail, PREFS, notifier)
    assert res.parser_errors == 1
    assert "parser_failed" in notifier.kinds()
    assert "no jobs found" in caplog.text
    assert res.inserted == 3  # the good email was still processed
    assert db.scalar("SELECT COUNT(*) FROM processed_emails WHERE email_id='linkedin_changed_template.eml'") == 0


def test_full_fixture_set_all_30_jobs_land_in_db(db, notifier):
    emails = [load_eml(f"linkedin_{i}.eml") for i in range(1, 6)] + [load_eml(f"naukri_{i}.eml") for i in range(1, 6)]
    res = run_discovery(db, FakeMail(emails), PREFS, notifier)
    assert res.parsed == 30
    assert res.inserted + res.duplicates + res.rejected == 30
    assert res.inserted > 0


# ---------------- PRF-03 TC-006 ----------------
def test_tc006_discovery_uses_the_users_search_preferences(db, notifier):
    prefs = SearchPrefs(keywords=["GenAI", "LLM", "Agent"], exp_min=1, exp_max=4, locations=["Mumbai"])
    email = naukri_email([
        ("GenAI Engineer", "Acme", "Mumbai", 1, "1-4 Yrs", "a-1"),            # matches everything
        ("Python Developer", "Beta", "Mumbai", 1, "1-4 Yrs", "b-2"),          # no keyword
        ("LLM Engineer", "Cyan", "Pune", 1, "1-4 Yrs", "c-3"),                # wrong location
        ("Agent Developer", "Delta", "Mumbai", 1, "6-9 Yrs", "d-4"),          # experience too high
    ])
    res = run_discovery(db, FakeMail([email]), prefs, notifier)
    assert [r["title"] for r in db.query("SELECT title FROM jobs")] == ["GenAI Engineer"]
    assert res.rejected == 3
    reasons = " | ".join(res.reject_reasons)
    assert "no keyword" in reasons and "not in preferences" in reasons and "outside" in reasons


# ---------------- DIS-02 ----------------
def test_tc014_job_posted_2_days_ago_is_kept():
    assert passes(job(days=2), PREFS, NOW)[0] is True


def test_tc015_job_posted_4_days_ago_is_dropped():
    keep, reason, _ = passes(job(days=4), PREFS, NOW)
    assert keep is False and "older than 3 days" in reason


def test_tc016_job_posted_exactly_3_days_ago_is_kept_boundary():
    assert passes(job(days=3), PREFS, NOW)[0] is True
    just_over = JobRaw(url="u", source="s", title="AI Engineer", company="c", posted_at=NOW - timedelta(days=3, seconds=1))
    assert passes(just_over, PREFS, NOW)[0] is False


def test_tc017_missing_posted_date_is_kept_and_flagged_consistently(db, notifier):
    keep, _, flags = passes(job(days=None), PREFS, NOW)
    assert keep is True and flags == ["posted_date_missing"]
    em = naukri_email([("GenAI Engineer", "Acme", "Mumbai", 1, "1-4 Yrs", "a-1")])
    em.html = em.html.replace('<span class="posted">1 day ago</span>', "")
    run_discovery(db, FakeMail([em]), PREFS, notifier)
    assert db.one("SELECT flags, posted_at FROM jobs")["flags"] == "posted_date_missing"


# ---------------- DIS-03 ----------------
def test_tc018_same_job_from_linkedin_and_naukri_gives_one_row(db, notifier):
    li = linkedin_email([("GenAI Engineer", "Acme AI Labs Pvt Ltd", "Mumbai, India", 1, "https://www.linkedin.com/comm/jobs/view/111?trk=a")])
    nk = naukri_email([("GenAI Engineer", "Acme AI Labs", "Mumbai", 1, "1-4 Yrs", "genai-engineer-acme-222")])
    res = run_discovery(db, FakeMail([li, nk]), PREFS, notifier)
    assert db.scalar("SELECT COUNT(*) FROM jobs") == 1
    assert res.inserted == 1 and res.duplicates == 1


def test_tc019_same_job_with_different_tracking_params_is_one_row(db, notifier):
    a = linkedin_email([("GenAI Engineer", "Acme", "Mumbai", 1, "https://www.linkedin.com/comm/jobs/view/999?trk=eml1&refId=A&utm_source=x")], "e1")
    b = linkedin_email([("GenAI Engineer", "Acme", "Mumbai", 1, "https://www.linkedin.com/jobs/view/999/?trackingId=Z&utm_campaign=y")], "e2")
    assert canonical_url(a.html and "https://www.linkedin.com/comm/jobs/view/999?trk=eml1&refId=A") == "https://www.linkedin.com/jobs/view/999"
    run_discovery(db, FakeMail([a, b]), PREFS, notifier)
    assert db.scalar("SELECT COUNT(*) FROM jobs") == 1
    assert canonical_url("https://www.naukri.com/job-listings-x-1?src=a&sid=2") == canonical_url("https://naukri.com/job-listings-x-1?utm_source=b")


def test_tc020_same_company_different_titles_give_two_rows(db, notifier):
    em = linkedin_email([
        ("GenAI Engineer", "Acme", "Mumbai", 1, "https://www.linkedin.com/jobs/view/1"),
        ("ML Engineer", "Acme", "Mumbai", 1, "https://www.linkedin.com/jobs/view/2")])
    run_discovery(db, FakeMail([em]), PREFS, notifier)
    assert db.scalar("SELECT COUNT(*) FROM jobs") == 2
    assert dedupe_key(job(title="GenAI Engineer")) != dedupe_key(job(title="ML Engineer"))


# ---------------- DIS-04 ----------------
def test_tc021_sales_and_bpo_titles_are_rejected():
    for title in ("Sales Executive", "BPO Associate"):
        keep, reason, _ = passes(job(title=title), PREFS, NOW)
        assert keep is False and "blacklisted" in reason


def test_tc022_genai_engineer_passes():
    assert passes(job(title="GenAI Engineer"), PREFS, NOW)[0] is True


def test_tc023_blacklist_and_whitelist_both_match_has_deterministic_documented_outcome():
    results = {passes(job(title="Senior AI Sales Engineer"), PREFS, NOW)[0] for _ in range(5)}
    assert results == {False}  # blacklist wins, every time
    assert "blacklist wins" in passes.__doc__


# ---------------- DIS-05 ----------------
def test_tc024_empty_gmail_result_raises_zero_jobs_alert(db, notifier):
    res = run_discovery(db, FakeMail([]), PREFS, notifier)
    assert res.inserted == 0
    alert = next(a for a in notifier.alerts if a["kind"] == "zero_jobs")
    assert alert["message"].startswith("0 jobs")


def test_tc025_expired_gmail_token_raises_auth_failed_alert_not_silent(db, notifier):
    res = run_discovery(db, FakeMail(error=MailAuthError("401 invalid_grant")), PREFS, notifier)
    assert res.auth_failed is True
    assert notifier.kinds() == ["auth_failed"]
    assert "auth failed" in notifier.alerts[0]["message"].lower()
