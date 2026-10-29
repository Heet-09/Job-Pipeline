"""Naukri scraper as the job source (replaces Gmail alerts as the way jobs are collected)."""
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from conftest import NOW
from helpers import FakeMail, linkedin_email, naukri_email
from jobagent.core import statuses as st
from jobagent.flows.f0_profile.prefs import SearchPrefs
from jobagent.flows.f1_discovery.naukri_scrape import extract_job, read_links
from jobagent.flows.f1_discovery.run import run_discovery, run_scraper_discovery
from jobagent.flows.f1_discovery.scraper_source import NaukriScraperSource, row_to_job
from jobagent.flows.f2_scoring.run import run_scoring

ROOT = Path(__file__).resolve().parents[2]
URL = "https://www.naukri.com/job-listings-genai-engineer-acme-mumbai-1-to-3-years-111?src=x&sid=1"
DESC = ("We are hiring a GenAI Engineer to build LLM agents with Python, LangGraph and LangChain. "
        "You will design retrieval pipelines, evaluate agents and ship to production. 1-3 years of experience required. " * 2).strip()


def row(**kw):
    base = dict(link=URL, job_role="GenAI Engineer", company="Acme AI Labs", exp_min_years=1, exp_max_years=3, package="Not Disclosed",
                work_mode="Hybrid", location="Mumbai", apply_on_company_site="No", posted="1 day ago",
                job_description=DESC, key_skills="Python, LangGraph, LangChain", status="ok")
    base.update(kw)
    return base


def source(rows):
    return NaukriScraperSource([r["link"] for r in rows], lambda urls: iter(rows))


# ---------------- field extraction from a Naukri-shaped page (real Chromium) ----------------
NAUKRI_LIKE = """<html><body>
<h1>Agentic AI Manager</h1>
<div class="styles_jd-header-comp-name__x"><a href="#">Vlink</a></div>
<div class="styles_jhc__exp__k">3-5 Yrs</div><div class="styles_jhc__salary__k">12-18 Lacs PA</div>
<div class="styles_jhc__location__k">Indore</div><span>Posted: 2 days ago</span>
<div class="styles_JDC__dang-inner-html__x">Hands-on experience with LLM agents and Python required.</div>
<div class="styles_key-skill__x"><a>Python</a><a>LLM</a><a>Python</a></div>
<button id="company-site-button">Apply on company site</button></body></html>"""


def test_extract_job_reads_every_field_from_a_naukri_shaped_page(page):
    page.set_content(NAUKRI_LIKE)
    r = extract_job(page, URL)
    assert (r["job_role"], r["company"], r["location"], r["posted"]) == ("Agentic AI Manager", "Vlink", "Indore", "2 days ago")
    assert (r["exp_min_years"], r["exp_max_years"], r["package"]) == (3, 5, "12-18 Lacs PA")
    assert r["key_skills"] == "Python, LLM" and "LLM agents" in r["job_description"]
    assert r["apply_on_company_site"] == "Yes" and r["status"] == "ok"


def test_read_links_handles_a_link_column_dates_and_duplicates(tmp_path):
    f = tmp_path / "l.xlsx"
    pd.DataFrame({"date": ["2026-10-23"] * 4, "link": [URL, URL, "https://www.linkedin.com/jobs/view/1", None]}).to_excel(f, index=False)
    assert read_links(f) == [URL, "https://www.linkedin.com/jobs/view/1"]
    g = tmp_path / "noheader.xlsx"
    pd.DataFrame([[URL], ["https://x.test/2"]]).to_excel(g, index=False, header=False)
    assert read_links(g) == [URL, "https://x.test/2"]


# ---------------- scraped row -> job ----------------
def test_row_to_job_maps_fields_and_keeps_the_full_description():
    j = row_to_job(row(package="12-18 Lacs PA"), NOW)
    assert (j.title, j.company, j.location, j.source) == ("GenAI Engineer", "Acme AI Labs", "Mumbai", "naukri_scraper")
    assert j.exp_text == "1-3 Yrs" and j.posted_at == NOW - timedelta(days=1)
    assert DESC in j.jd_text and "Key skills: Python, LangGraph, LangChain" in j.jd_text and "Salary: 12-18 Lacs PA" in j.jd_text
    assert "Not Disclosed" not in row_to_job(row(), NOW).jd_text


@pytest.mark.parametrize("bad", [dict(status="job expired/removed (redirected to search page)"), dict(status="skipped (not a Naukri job listing link)"),
                                 dict(status="error: timeout"), dict(job_role=""), dict(company=float("nan"))])
def test_row_to_job_ignores_rows_that_are_not_real_jobs(bad):
    assert row_to_job(row(**bad), NOW) is None


def test_row_to_job_open_ended_experience_and_missing_values():
    assert row_to_job(row(exp_max_years=float("nan")), NOW).exp_text == "1+ Yrs"
    j = row_to_job(row(exp_min_years=float("nan"), exp_max_years=float("nan"), location=float("nan"), posted=float("nan")), NOW)
    assert j.exp_text is None and j.location is None and j.posted_at is None


def test_week_old_posting_is_parsed_as_7_days():
    assert row_to_job(row(posted="1 week ago"), NOW).posted_at == NOW - timedelta(days=7)


@pytest.mark.parametrize("title", ["Artificial Intelligence Engineer", "Senior Data Scientist", "Machine Learning Engineer", "Agentic AI Manager"])
def test_default_title_keywords_accept_common_ai_titles_found_in_real_data(title):
    from jobagent.flows.f1_discovery.prefilter import passes
    assert passes(row_to_job(row(job_role=title), NOW), SearchPrefs(), NOW)[0] is True


def test_four_plus_letter_keywords_match_longer_words_but_the_blacklist_stays_whole_word():
    from jobagent.flows.f1_discovery.prefilter import passes
    prefs = SearchPrefs(keywords=["Agent", "LLM"])
    assert passes(row_to_job(row(job_role="Agentic AI Manager"), NOW), prefs, NOW)[0] is True
    assert passes(row_to_job(row(job_role="LLMOps Engineer"), NOW), prefs, NOW)[0] is False   # 3-letter keyword stays exact
    keep, reason, _ = passes(row_to_job(row(job_role="Salesforce AI Agent Developer"), NOW), prefs, NOW)
    assert keep is True                                                                      # 'sales' must not catch 'Salesforce'


def test_the_shipped_search_prefs_file_loads_and_accepts_the_real_titles_from_your_data():
    from jobagent.flows.f0_profile.prefs import load_prefs
    from jobagent.flows.f1_discovery.prefilter import passes
    prefs = load_prefs(ROOT / "config" / "search_prefs.yaml")
    for title in ("Agentic Ai Manager", "Data Scientist", "Artificial Intelligence Engineer"):
        assert passes(row_to_job(row(job_role=title), NOW), prefs, NOW)[0] is True, title


# ---------------- scraper discovery ----------------
def test_scraped_jobs_are_inserted_with_the_full_jd_and_filtered_like_email_jobs(db, notifier):
    rows = [row(),
            row(link="https://www.naukri.com/job-listings-sales-exec-2", job_role="Sales Executive", company="Zed"),     # blacklisted
            row(link="https://www.naukri.com/job-listings-old-3", job_role="LLM Engineer", company="Old Co", posted="2 weeks ago"),  # too old
            row(link="https://www.naukri.com/job-listings-gone-4", status="job expired/removed (redirected to search page)")]
    res = run_scraper_discovery(db, source(rows), SearchPrefs(), notifier)
    assert (res.scraped, res.parsed, res.expired, res.inserted, res.rejected) == (4, 3, 1, 1, 2)
    j = db.one("SELECT * FROM jobs")
    assert j["title"] == "GenAI Engineer" and j["source"] == "naukri_scraper" and j["status"] == st.DISCOVERED
    assert DESC in j["jd_raw"] and j["canonical_url"] == "https://naukri.com/job-listings-genai-engineer-acme-mumbai-1-to-3-years-111"
    assert db.one("SELECT to_status, note FROM job_history")["note"] == "from naukri_scraper"


def test_running_the_scraper_twice_adds_nothing_new(db, notifier):
    rows = [row()]
    run_scraper_discovery(db, source(rows), SearchPrefs(), notifier)
    again = run_scraper_discovery(db, source(rows), SearchPrefs(), notifier)
    assert again.inserted == 0 and again.duplicates == 1 and db.scalar("SELECT COUNT(*) FROM jobs") == 1
    assert "zero_jobs" in notifier.kinds()


def test_same_job_from_an_alert_email_and_the_scraper_is_one_row(db, notifier):
    em = naukri_email([("GenAI Engineer", "Acme AI Labs", "Mumbai", 1, "1-3 Yrs", "genai-engineer-acme-mumbai-1-to-3-years-111")])
    run_discovery(db, FakeMail([em]), SearchPrefs(), notifier)
    res = run_scraper_discovery(db, source([row()]), SearchPrefs(), notifier)
    assert db.scalar("SELECT COUNT(*) FROM jobs") == 1 and res.duplicates == 1


def test_all_links_failing_raises_a_source_failed_alert(db, notifier):
    rows = [row(link=f"https://www.naukri.com/job-listings-x-{i}", status="error: Access Denied") for i in range(3)]
    res = run_scraper_discovery(db, source(rows), SearchPrefs(), notifier)
    assert res.inserted == 0 and res.scrape_errors == 3
    a = next(a for a in notifier.alerts if a["kind"] == "source_failed")
    assert "all 3 links failed" in a["message"] and "Access Denied" in a["message"]


def test_scraper_crash_is_reported_not_raised(db, notifier):
    def boom(urls):
        raise RuntimeError("browser could not start")
    res = run_scraper_discovery(db, NaukriScraperSource(["u"], boom), SearchPrefs(), notifier)
    assert res.scrape_errors == 1 and notifier.kinds() == ["source_failed"]


def test_dry_run_scrapes_and_filters_but_writes_nothing(db, notifier):
    from jobagent.core.db import Database
    dry = Database(":memory:", dry_run=True, clock=db.clock)
    res = run_scraper_discovery(dry, source([row()]), SearchPrefs(), notifier)
    assert res.inserted == 1 and dry.skipped_writes and dry.scalar("SELECT COUNT(*) FROM jobs") == 0


def test_scoring_uses_the_stored_jd_and_never_refetches(db, profile, settings, notifier):
    run_scraper_discovery(db, source([row()]), SearchPrefs(), notifier)

    def no_network(url):
        raise AssertionError("fetch must not be called when the scraper already stored the JD")
    run_scoring(db, profile, no_network, None, settings)
    j = db.one("SELECT status FROM jobs")
    s = db.one("SELECT llm_score FROM job_scores")
    assert j["status"] == st.SCORED and s["llm_score"] >= 70
    assert [h["to_status"] for h in db.query("SELECT to_status FROM job_history ORDER BY id")] == ["DISCOVERED", "EXTRACTED", "SCORED"]


# ---------------- your real scraped data ----------------
REAL = ROOT / "Jobs_output.xlsx"


@pytest.mark.skipif(not REAL.exists(), reason="Jobs_output.xlsx (your real scraper output) not present")
def test_real_scraped_rows_flow_through_discovery_and_scoring(db, profile, settings, notifier):
    df = pd.read_excel(REAL)
    rows = df.to_dict("records")
    ok_rows = [r for r in rows if r["status"] == "ok"]
    assert len(ok_rows) > 100 and all(row_to_job(r, NOW) for r in ok_rows)           # every real 'ok' row converts to a job
    prefs = SearchPrefs(max_age_days=365)                                            # real rows are of mixed age; judge parsing, not freshness
    res = run_scraper_discovery(db, NaukriScraperSource(["x"] * len(rows), lambda urls: iter(rows)), prefs, notifier)
    assert res.scraped == len(rows) and res.parsed == len(ok_rows)
    assert res.inserted > 50 and res.inserted + res.duplicates + res.rejected == res.parsed
    assert db.scalar("SELECT COUNT(*) FROM jobs WHERE jd_raw IS NULL OR length(jd_raw) < 50") <= res.inserted * 0.05   # real JDs were stored

    def no_network(url):
        raise AssertionError("no fetch expected")
    summary = run_scoring(db, profile, no_network, None, settings, batch=1000)
    assert summary.processed == res.inserted and summary.failed == 0 and summary.extraction_failed == 0
    buckets = {r["status"]: r["n"] for r in db.query("SELECT status, COUNT(*) n FROM jobs GROUP BY status")}
    assert sum(buckets.values()) == res.inserted and set(buckets) <= {st.SCORED, st.MAYBE, st.REJECTED}
    print("\nREAL DATA:", dict(ok_rows=len(ok_rows), inserted=res.inserted, duplicates=res.duplicates, filtered=res.rejected, buckets=buckets))
